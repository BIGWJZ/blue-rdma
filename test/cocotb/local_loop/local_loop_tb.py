import sys
import os
import cocotb
import cocotb_test.simulator
import logging


from cocotbext.axi import (AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamMonitor, AxiStreamFrame)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pcie_tb import PcieTb
from cmac_tb import CmacTb
from ringbufs import *

tests_dir = os.path.dirname(__file__)
rtl_dir = tests_dir
cocotb_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
prm_dir = cocotb_dir + '/primitives'

USER_BAR_ID = 1

CMD_Q_H2C_RINGBUF_START_PA = 0x0
CMD_Q_C2H_RINGBUF_START_PA = 0x1000
SEND_Q_RINGBUF_START_PA = 0x2000
META_REPORT_Q_RINGBUF_START_PA = 0x3000

NIC_CONFIG_GATEWAY = 0x00000001
NIC_CONFIG_IPADDR = 0x11223344
NIC_CONFIG_NETMASK = 0xFFFFFFFF
NIC_CONFIG_MACADDR = 0xAABBCCDDEEFF

class LocalLoopTb:
    def __init__(self, dut):
        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)
        
        self.pcie_tb = PcieTb(dut)
        self.clock = self.pcie_tb.clock
        self.resetn = self.pcie_tb.resetn
        # self.cmac_tb = CmacTb(dut)
        
        self.udp_rx = AxiStreamBus.from_prefix(dut, "udp_rx")
        self.udp_tx = AxiStreamBus.from_prefix(dut, "udp_tx")
        self.dummySink = AxiStreamMonitor(self.udp_tx, self.clock, self.resetn)
        
    async def start(self):
        self.log.info("Blue-RDMA Local Loop TestBench Starting...")
        await self.pcie_tb.start()
        self.bar = self.pcie_tb.get_bar(USER_BAR_ID)
        self.mem = self.pcie_tb.get_host_mem()
        
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

@cocotb.test(timeout_time=10000000, timeout_unit="ns")          
async def bar_test(dut):
    tb = LocalLoopTb(dut)
    await tb.start()

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
        # timescale="1ns/1ps",
        sim_build=sim_build
    )
    
if __name__ == "__main__":
    test_rdma()