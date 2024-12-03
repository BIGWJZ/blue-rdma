import os
import mmap
import struct
import ctypes
import logging

from ringbufs import *

RING_BUFFER_SIZE = 4 * 1024  # 4K, 1K for each rbuf among {cmdReqQ, cmdRespQ, sQ, rQ}
HUGE_PAGE_BYTE_CNT = 2 * 1024 * 1024 # 2M

NIC_CONFIG_GATEWAY = 0x00000001
NIC_CONFIG_IPADDR = 0x11223344
NIC_CONFIG_NETMASK = 0xFFFFFFFF
NIC_CONFIG_MACADDR = 0xAABBCCDDEEFF

USER_BAR_SIZE = 1024 * 1024 #1M

libc = ctypes.CDLL("libc.so.6") 
mlock = libc.mlock
munlock = libc.munlock

def va_to_pa(virt_addr, is_huge_page = False):
    with open("/proc/self/pagemap", "rb") as pagemap:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pagemap.seek(virt_addr // page_size * 8)
        entry = struct.unpack("Q", pagemap.read(8))[0]
        if (entry & (1 << 63)) == 0:
            print("Error: Cannot transfer va:0x%x to pa" % virt_addr)
            raise RuntimeError("PageMap Error: Not Present")
        pfn = entry & ((1 << 54) - 1)
        if is_huge_page is True:
            pa = pfn * page_size + (virt_addr % HUGE_PAGE_BYTE_CNT)
        else:
            pa = pfn * page_size + (virt_addr % page_size)
        return pa
    
def get_va_from_mem(mem):
        return ctypes.addressof(ctypes.c_char.from_buffer(mem))
    
class HugeMemManager:
    def __init__(self, mnt_path):
        if not os.path.exists(mnt_path) or not os.path.isdir(mnt_path):
            raise RuntimeError("Invalid Huge Page Mount Path")
        self.mnt_path = mnt_path
        self.mem_id = 0
        self.mem_cache = {}
        
    def allocate(self, page_num):
        cur_id = self.mem_id
        path = self.mnt_path + '/bluerdma' + str(cur_id)
        print("create hugepage file in ", path)
        self.mem_id = self.mem_id + 1
        byte_size = HUGE_PAGE_BYTE_CNT * page_num
        with open(path, "wb") as f:
            f.truncate(byte_size)  
        with open(path, "r+b") as f:
            mem = mmap.mmap(f.fileno(), byte_size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.mem_cache[cur_id] = mem
        return mem, cur_id
    
    def close(self, mem_id):
        if mem_id in self.mem_cache:
            self.mem_cache[mem_id].close
            del self.mem_cache[mem_id]
            
    def close_all(self):
        for idx in range(self.mem_id):
            self.close(idx)

class BlueRdmaDriver:
    def __init__(self, bar_mmap_filepath) -> None:
        self.log = logging.getLogger("Bdma-Rdma Driver")
        self.log.setLevel(logging.INFO)
        self.bar = BlueRdmaBarInterface(bar_mmap_filepath)
        
        self.cmdReqQ_mem, self.cmdReqQ_pa = self.alloc_dma_mem(RING_BUFFER_SIZE)
        self.cmd_req_queue = RingbufCommandReqQueue(
            memoryview(self.cmdReqQ_mem), self.cmdReqQ_pa, bar_host=self.bar)
        
        self.cmdRespQ_mem, self.cmdRespQ_pa = self.alloc_dma_mem(RING_BUFFER_SIZE)
        self.cmd_resp_queue = RingbufCommandRespQueue(
            memoryview(self.cmdRespQ_mem), self.cmdRespQ_pa, bar_host=self.bar)
        
        self.sQ_mem, self.sQ_pa = self.alloc_dma_mem(RING_BUFFER_SIZE)
        self.send_queue = RingbufSendQueue(
            memoryview(self.sQ_mem), self.sQ_pa, bar_host=self.bar)
        
        self.rptQ_mem, self.rptQ_pa = self.alloc_dma_mem(RING_BUFFER_SIZE)
        self.meta_report_queue = RingbufMetaReportQueue(
            memoryview(self.rptQ_mem), self.rptQ_pa, bar_host=self.bar)
        
        self.cmd_req_queue.put_desc_set_udp_param(
            NIC_CONFIG_GATEWAY, NIC_CONFIG_NETMASK, NIC_CONFIG_IPADDR, NIC_CONFIG_MACADDR)
        self.log.info("init: writing UDP settings...")
        self.cmd_req_queue.sync_pointers()

        self.cmd_resp_queue.deq_blocking()

        self.pgt_bufs = []
        self.log.info("init: done! Use *memory_register* for rdma...")
        
    def alloc_dma_mem(self, size):
        dma_mem = mmap.mmap(-1, size)
        for byte_idx in range(size):
            dma_mem[byte_idx] = 0
        start_va = get_va_from_mem(dma_mem)
        start_pa = va_to_pa(start_va)
        lock_rv = mlock(ctypes.c_void_p(start_va), RING_BUFFER_SIZE)
        if lock_rv != 0:
            raise RuntimeError("mlock failed!")
        return (dma_mem, start_pa)
    
    def destroy_dma_mem(self, mem):
        start_va = get_va_from_mem(mem)
        lock_rv = munlock(start_va, RING_BUFFER_SIZE)
        if lock_rv != 0:
            raise RuntimeError("munlock failed!")
        mem.close()
        
    def stop(self):
        self.destroy_dma_mem(self.cmdReqQ_mem)
        self.destroy_dma_mem(self.cmdRespQ_mem)
        self.destroy_dma_mem(self.sQ_mem)
        self.destroy_dma_mem(self.rptQ_mem)
        for pgt_mem in self.pgt_bufs:
            self.destroy_dma_mem(pgt_mem)
        

    def memory_register(self, user_buf, buf_va, length, key, pd_handle, pgt_offset, 
                        acc_flag=MemAccessTypeFlag.IBV_ACCESS_LOCAL_WRITE | MemAccessTypeFlag.IBV_ACCESS_REMOTE_READ | MemAccessTypeFlag.IBV_ACCESS_REMOTE_WRITE):
        self.cmd_req_queue.put_desc_update_mr_table(
            base_va=buf_va,
            length=length,
            key=key,
            pd_handle=pd_handle,
            pgt_offset=pgt_offset,
            acc_flag=acc_flag,
        )
        
        pgt_buf, pgt_start_pa, pgt_len = self.gen_pgt_entries(buf_va, len)
        
        self.pgt_bufs.append(pgt_buf)

        self.cmd_req_queue.put_desc_update_pgt(
            dma_addr=pgt_start_pa,
            dma_length=pgt_len,
            start_index=pgt_offset,
        )
        
        self.cmd_req_queue.sync_pointers()
        for _ in range(2):
            self.cmd_resp_queue.deq_blocking()
        self.log.info("done memory register: mr_va:0x%x, mr_pa:0x%x, mr_len:%d, pgt_va:0x%x, pgt_pa:0x%x, pgt_len:%d"
                      % (buf_va, va_to_pa(buf_va), length, get_va_from_mem(pgt_buf), pgt_start_pa, pgt_len))
    
    def create_qp(self, qpn, peer_qpn, pd_handle, qp_type, acc_type, pmtu):
        self.cmd_req_queue.put_desc_update_qp(
            qpn=qpn,
            peer_qpn=peer_qpn,
            pd_handler=pd_handle,
            qp_type=qp_type,
            acc_flag=acc_type,
            pmtu=pmtu,
        )
        self.cmd_req_queue.sync_pointers()
        self.cmd_resp_queue.deq_blocking()
        
    def gen_pgt_entries(self, buf_va, buf_len):
        # Warning: only support 1 huge_page now
        entries_num = (buf_va + buf_len) // HUGE_PAGE_BYTE_CNT - buf_va // HUGE_PAGE_BYTE_CNT + 1
        pgt_len = entries_num * 8
        pgt_mem, pgt_start_pa = self.alloc_dma_mem(pgt_len)
        buf_pa = va_to_pa(buf_va, is_huge_page=True)
        pgt_mem[0:7] = bytes(buf_pa)
        return pgt_mem, pgt_start_pa, pgt_len
        


class BlueRdmaBarInterface:
    def __init__(self, bar_mmap_filepath) -> None:
        self.bar_mmap_filepath = bar_mmap_filepath
        try: 
            self.bar_mmap_fd = os.open(bar_mmap_filepath, os.O_RDWR)
            self.bar_size = USER_BAR_SIZE
            print(self.bar_mmap_fd, self.bar_size)
            self.mapped_memory = mmap.mmap(self.bar_mmap_fd, self.bar_size)
        except PermissionError:
            print(f"Error: Permission denied to access '{bar_mmap_filepath}'. Try running as root.")
        except FileNotFoundError:
            print(f"Error: Device file '{bar_mmap_filepath}' not found.")

        print("BAR Debug", self.mapped_memory[0:16])

    def stop(self):
        self.mapped_memory.close()
        os.close(self.bar_mmap_fd)

    def write_csr_non_blocking(self, addr, value:int):
        print("BAR Debug: write bar addr:%d, value:%d" % (addr, value))
        self.mapped_memory[addr:addr+4] = value.to_bytes(4, byteorder='big')

    def write_csr_blocking(self, addr, value:int):
        self.write_csr_non_blocking(addr, value)

    def read_csr_blocking(self, addr) -> int:
        value_bytes = self.mapped_memory[addr:addr+4]
        return int.from_bytes(value_bytes, byteorder='big')

