import sys
import os
import cocotb
import cocotb_test.simulator

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ringbufs import *
from bluerdma_tb import *

tests_dir = os.path.dirname(__file__)
rtl_dir = tests_dir
cocotb_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
prm_dir = cocotb_dir + '/primitives'

# Local Looping Settings
SEND_SIDE_KEY = 0x6622
RECV_SIDE_KEY = SEND_SIDE_KEY
PKEY_INDEX = 0

SEND_SIDE_QPN = 0x6611
SEND_SIDE_PD_HANDLER = 0x6611  # in practise, this should be returned by hardware
RECV_SIDE_QPN= SEND_SIDE_QPN

RECV_SIDE_IP = NIC_CONFIG_IPADDR
RECE_SIDE_MAC = NIC_CONFIG_MACADDR
SEND_SIDE_PSN = 0x0

PMTU_VALUE_FOR_TEST = PMTU.IBV_MTU_256

SEND_BYTE_COUNT = PMTU_VALUE_FOR_TEST

USER_BASE_VA = 0x12345600000  # map to MR_0_START_PA : MR_O_START_PA + MR_0_LENGTH

REQ_SIDE_VA_OFFSET = 0x200000
REQ_SIDE_VA_ADDR = (USER_BASE_VA & HUGEPAGE_2M_ADDR_MASK) + REQ_SIDE_VA_OFFSET
REQ_SIDE_PA_ADDR = MR_0_START_PA + REQ_SIDE_VA_OFFSET

RESP_SIDE_VA_OFFSET = 0x0
RESP_SIDE_VA_ADDR = (USER_BASE_VA & HUGEPAGE_2M_ADDR_MASK) + RESP_SIDE_VA_OFFSET
RESP_SIDE_PA_ADDR = MR_0_START_PA + RESP_SIDE_VA_OFFSET

class AxiStreamConnector:
    def __init__(self, tx_bus: AxiStreamBus, rx_bus: AxiStreamBus, clock, resetn):
        self.tx_sink = AxiStreamSink(tx_bus, clock, resetn, reset_active_level=False)
        self.rx_source = AxiStreamSource(rx_bus, clock, resetn, reset_active_level=False)
    
    async def relay(self):
        while True:
            frame = await self.tx_sink.recv()
            print("Blue-Rdma DEBUG: recv frame from udp_tx: ", frame)
            await self.rx_source.send(frame)
            
    def connect(self):
        cocotb.start_soon(self.relay())

async def tb_init(dut):
    tb = BlueRdmaTb(dut)
    connector = AxiStreamConnector(tb.udp_tx, tb.udp_rx, tb.clock, tb.resetn)
    connector.connect()
    
    await tb.start()
    
    await tb.memory_register(
        va=USER_BASE_VA,
        length=MR_0_LENGTH,
        pa=MR_0_START_PA,
        key=SEND_SIDE_KEY,
        pgt_offset=0x0,
        pd_handle=SEND_SIDE_PD_HANDLER
    )
    
    await tb.create_qp(
        qpn=SEND_SIDE_QPN,
        peer_qpn=RECV_SIDE_QPN,
        pd_handler=SEND_SIDE_PD_HANDLER,
        qp_type=TypeQP.IBV_QPT_RC,
        acc_flag=MemAccessTypeFlag.IBV_ACCESS_LOCAL_WRITE | MemAccessTypeFlag.IBV_ACCESS_REMOTE_READ | MemAccessTypeFlag.IBV_ACCESS_REMOTE_WRITE,
        pmtu=PMTU_VALUE_FOR_TEST,
    )
    
    return tb
    
# Test 1: Write Remote Data

@cocotb.test(timeout_time=10000000, timeout_unit="ns")          
async def local_loop_test_write(dut):
    print("BlueRdma local_loop_write_tb: Starting...")
    tb = await tb_init(dut)
    
    sgl = [
        SendQueueReqDescFragSGE(
            F_LKEY=SEND_SIDE_KEY, F_LEN=SEND_BYTE_COUNT, F_LADDR=REQ_SIDE_VA_ADDR),
    ]

    tb.send_queue.put_work_request(
        opcode=WorkReqOpCode.IBV_WR_RDMA_WRITE,
        is_first=True,
        is_last=True,
        sgl=sgl,
        r_va=RESP_SIDE_VA_ADDR,
        r_key=RECV_SIDE_KEY,
        r_ip=RECV_SIDE_IP,
        r_mac=RECE_SIDE_MAC,
        dqpn=RECV_SIDE_QPN,
        psn=SEND_SIDE_PSN,
        pmtu=PMTU_VALUE_FOR_TEST,
        send_flag=WorkReqSendFlag.IBV_SEND_SIGNALED,
    )
    
    for i in range(SEND_BYTE_COUNT):
        tb.mem[REQ_SIDE_PA_ADDR+i] = (0xBB + i) & 0xFF
        tb.mem[RESP_SIDE_PA_ADDR+i] = 0
        
    await tb.send_queue.sync_pointers()
    
    rpt = await tb.meta_report_queue.deq_blocking()
    print("receive meta report: ", MeatReportQueueDescBthReth.from_buffer_copy(rpt))
    assert_descriptor_reth(rpt, RdmaOpCode.RDMA_WRITE_ONLY)
    
    ack_rpt = await tb.meta_report_queue.deq_blocking()
    assert_descriptor_ack(ack_rpt)

    src_data = tb.mem[REQ_SIDE_PA_ADDR  : REQ_SIDE_PA_ADDR+SEND_BYTE_COUNT]
    dst_data = tb.mem[RESP_SIDE_PA_ADDR : RESP_SIDE_PA_ADDR+SEND_BYTE_COUNT]
    
    if src_data != dst_data:
        print("Error: DMA Target mem is not the same as source mem")
        for idx in range(len(src_data)):
            if src_data[idx] != dst_data[idx]:
                print("id:", idx,
                      "src: ", hex(src_data[idx]),
                      "dst: ", hex(dst_data[idx])
                      )
        raise SystemExit
    else:
        print("local_loop_tb: PASS RDMA Write Test!")
        
# Test 2: Read Remote Data
@cocotb.test(timeout_time=10000000, timeout_unit="ns")          
async def local_loop_test_read(dut):    
    print("BlueRdma local_loop_read_tb: Starting...")
    tb = await tb_init(dut)
    
    sgl = [
        SendQueueReqDescFragSGE(
            F_LKEY=SEND_SIDE_KEY, F_LEN=SEND_BYTE_COUNT, F_LADDR=RESP_SIDE_VA_ADDR),
    ]
    tb.send_queue.put_work_request(
        opcode=WorkReqOpCode.IBV_WR_RDMA_READ,
        is_first=True,
        is_last=True,
        sgl=sgl,
        r_va=REQ_SIDE_VA_ADDR,
        r_key=RECV_SIDE_KEY,
        r_ip=RECV_SIDE_IP,
        r_mac=RECE_SIDE_MAC,
        dqpn=RECV_SIDE_QPN,
        psn=SEND_SIDE_PSN,
        pmtu=PMTU_VALUE_FOR_TEST,
        send_flag=WorkReqSendFlag.IBV_SEND_SIGNALED,
    )
    
    await tb.send_queue.sync_pointers()
    rpt = await tb.meta_report_queue.deq_blocking()  # packet meta report first
    
    parsed_report = MeatReportQueueDescBthReth.from_buffer_copy(rpt)
    if parsed_report.F_BTH.F_OPCODE != RdmaOpCode.RDMA_READ_REQUEST:
        print(f"Error: Error at read test, read request opcode not right, "
              f"received=0x{hex(parsed_report.F_BTH.F_OPCODE)},",
              f"expected={hex(RdmaOpCode.RDMA_READ_REQUEST)}")
        raise SystemExit
    else:
        print("local_loop_tb: PASS RDMA Read Test!")
    

def test_rdma():
    dut = "mkCocotbTop"
    module = os.path.splitext(os.path.basename(__file__))[0]
    toplevel = dut

    verilog_sources = [
        os.path.join(rtl_dir, f"{dut}.v"),
        os.path.join(prm_dir, "LookupTableLoad.v")
    ]

    sim_build = os.path.join(tests_dir, "sim_build", dut)

    cocotb_test.simulator.run(
        python_search=[tests_dir],
        verilog_sources=verilog_sources,
        toplevel=toplevel,
        module=module,
        timescale="1ns/1ps",
        sim_build=sim_build
    )
    
if __name__ == "__main__":
    test_rdma()