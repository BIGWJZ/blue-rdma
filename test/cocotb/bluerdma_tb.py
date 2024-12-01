import logging
from cocotbext.axi import (AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamMonitor, AxiStreamFrame)
from ringbufs import *
from utils import *
from bdma_tb import BdmaTb

USER_BAR_ID = 1

HUGEPAGE_2M_ADDR_MASK = 0xFFFFFFFFFFE00000
HUGEPAGE_2M_BYTE_CNT = 0x200000
PGT_ENTRY_SIZE = 0x08  

# TEST MEMORY ALLOCATION

# descriptor ring buffer space, 4KB * 4, start from 0
CMD_Q_H2C_RINGBUF_START_PA = 0x0
CMD_Q_C2H_RINGBUF_START_PA = 0x1000
SEND_Q_RINGBUF_START_PA = 0x2000
META_REPORT_Q_RINGBUF_START_PA = 0x3000

# page table space, 48KB, start from 16KB
# max 16K PGT entries
PGT_START_PA = 0x4000

# user data space 0, 2MB * 10, start from 2MB
MR_0_START_PA = 0x200000
MR_0_PTE_COUNT = 0x10
MR_0_LENGTH = MR_0_PTE_COUNT * HUGEPAGE_2M_BYTE_CNT

# user data space 1, 2MB * 10, start from 22MB
MR_1_START_PA = 0x200000 + MR_0_LENGTH
MR_1_PTE_COUNT = 0x10
MR_1_LENGTH = MR_1_PTE_COUNT * HUGEPAGE_2M_BYTE_CNT

# udp configurations
NIC_CONFIG_GATEWAY = 0x00000001
NIC_CONFIG_IPADDR = 0x11223344
NIC_CONFIG_NETMASK = 0xFFFFFFFF
NIC_CONFIG_MACADDR = 0xAABBCCDDEEFF

class BlueRdmaTb:
    def __init__(self, dut):
        self.log = logging.getLogger("Blue-Rdma LocalLoopTb")
        self.log.setLevel(logging.DEBUG)
        
        self.bdma_tb = BdmaTb(dut)
        self.clock = self.bdma_tb.clock
        self.resetn = self.bdma_tb.resetn
        # self.cmac_tb = CmacTb(dut)
        
        self.udp_rx = AxiStreamBus.from_prefix(dut, "udp_rx")
        self.udp_tx = AxiStreamBus.from_prefix(dut, "udp_tx")
        self.dummySink = AxiStreamMonitor(self.udp_tx, self.clock, self.resetn)
        
    async def start(self):
        self.log.info("Blue-RDMA Local Loop TestBench Starting...")
        await self.bdma_tb.start()
        self.bar = self.bdma_tb.get_bar(USER_BAR_ID)
        self.mem = self.bdma_tb.get_host_mem()
        
        self.cmd_req_queue = RingbufCommandReqQueue(
            self.mem, CMD_Q_H2C_RINGBUF_START_PA, bar_host=self.bar)
        self.cmd_resp_queue = RingbufCommandRespQueue(
            self.mem, CMD_Q_C2H_RINGBUF_START_PA, bar_host=self.bar)
        self.send_queue = RingbufSendQueue(
            self.mem, SEND_Q_RINGBUF_START_PA, bar_host=self.bar)
        self.meta_report_queue = RingbufMetaReportQueue(
            self.mem, META_REPORT_Q_RINGBUF_START_PA, bar_host=self.bar)
        
        await self.cmd_req_queue.start()
        await self.cmd_resp_queue.start()
        await self.send_queue.start()
        await self.meta_report_queue.start()
        
        self.log.info("Writing UDP parameters...")
        
        self.cmd_req_queue.put_desc_set_udp_param(
            NIC_CONFIG_GATEWAY, NIC_CONFIG_NETMASK, NIC_CONFIG_IPADDR, NIC_CONFIG_MACADDR)
        
        await self.cmd_req_queue.sync_pointers()
        await self.cmd_resp_queue.deq_blocking()
        
    async def memory_register(self, va:int, length:int, pa:int, key, pgt_offset, pd_handle):
        self.cmd_req_queue.put_desc_update_mr_table(
            base_va=va,
            length=length,
            key=key,
            pd_handle=pd_handle,
            pgt_offset=pgt_offset,
            acc_flag=MemAccessTypeFlag.IBV_ACCESS_LOCAL_WRITE | MemAccessTypeFlag.IBV_ACCESS_REMOTE_READ | MemAccessTypeFlag.IBV_ACCESS_REMOTE_WRITE,
        )
        
        pgt_entry_num = length // HUGEPAGE_2M_BYTE_CNT
        PgtEntries = c_longlong * pgt_entry_num
        entries = PgtEntries()
        
        # Only for simulation, the function need to get real PA and pin the memory on the real device 
        for i in range(len(entries)):
            entries[i] = pa + i * HUGEPAGE_2M_BYTE_CNT
            
        pgtBytes = bytes(entries)
        self.mem[PGT_START_PA : PGT_START_PA + len(pgtBytes)] = pgtBytes
        
        self.cmd_req_queue.put_desc_update_pgt(
            dma_addr=PGT_START_PA,
            dma_length=len(pgtBytes),
            start_index=pgt_offset,
        )
        
        self.log.info("Memory Region Register: start_va 0x%x, length 0x%x, mapped_pa 0x%x, mapped_entries %d, pgt_pa 0x%x"
                      % (va, length, pa, pgt_entry_num, PGT_START_PA))
        
        await self.cmd_req_queue.sync_pointers()
        for _ in range(2):
            await self.cmd_resp_queue.deq_blocking()
        
    async def create_qp(self, qpn, peer_qpn, pd_handler, qp_type, acc_flag, pmtu):
        self.cmd_req_queue.put_desc_update_qp(
            qpn=qpn,
            peer_qpn=peer_qpn,
            pd_handler=pd_handler,
            qp_type=qp_type,
            acc_flag=acc_flag,
            pmtu=pmtu,
        )
        await self.cmd_req_queue.sync_pointers()
        await self.cmd_resp_queue.deq_blocking()
        
        
