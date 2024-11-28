import logging
import cocotb
import cocotb.clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb.clock import Clock

from cocotbext.axi import (AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamMonitor, AxiStreamFrame)

def init_signal(sig, width=None, initval=None):
    if sig is None:
        return None
    if width is not None:
        assert len(sig) == width
    if initval is not None:
        sig.setimmediatevalue(initval)
    return sig

# Dummy Cmac Device, Do not support flow control
class CmacDevice:
    def __init__(self, 
                gt_txusrclk2 = None,
                
                rx_axis_bus = None,
                tx_axis_bus = None,
                tx_ovfout   = None,
                tx_unfout   = None,
                
                stat_rx_aligned        = None,        
                stat_rx_pause_req      = None,
                ctl_rx_enable          = None,
                ctl_rx_force_resync    = None,
                ctl_rx_test_pattern    = None,
                ctl_rx_reset           = None,
                ctl_rx_pause_enable    = None,
                ctl_rx_pause_ack       = None,
                ctl_rx_enable_gcp      = None,
                ctl_rx_check_mcast_gcp = None,
                ctl_rx_check_ucast_gcp = None,
                ctl_rx_check_sa_gcp    = None,
                ctl_rx_check_etype_gcp = None,
                ctl_rx_check_opcode_gcp= None,
                ctl_rx_enable_pcp      = None,
                ctl_rx_check_mcast_pcp = None,
                ctl_rx_check_ucast_pcp = None,
                ctl_rx_check_sa_pcp    = None,
                ctl_rx_check_etype_pcp = None,
                ctl_rx_check_opcode_pcp= None,
                ctl_rx_enable_gpp      = None,
                ctl_rx_check_mcast_gpp = None,
                ctl_rx_check_ucast_gpp = None,
                ctl_rx_check_sa_gpp    = None,
                ctl_rx_check_etype_gpp = None,
                ctl_rx_check_opcode_gpp= None,
                ctl_rx_enable_ppp      = None,
                ctl_rx_check_mcast_ppp = None,
                ctl_rx_check_ucast_ppp = None,
                ctl_rx_check_sa_ppp    = None,
                ctl_rx_check_etype_ppp = None,
                ctl_rx_check_opcode_ppp= None,
                
                ctl_tx_enable       = None,       
                ctl_tx_test_pattern = None,
                ctl_tx_send_idle    = None,
                ctl_tx_send_rfi     = None,
                ctl_tx_send_lfi     = None,
                ctl_tx_pause_enable = None,
                ctl_tx_pause_req    = None,
                ctl_tx_pause_quanta0= None,
                ctl_tx_pause_quanta1= None,
                ctl_tx_pause_quanta2= None,
                ctl_tx_pause_quanta3= None,
                ctl_tx_pause_quanta4= None,
                ctl_tx_pause_quanta5= None,
                ctl_tx_pause_quanta6= None,
                ctl_tx_pause_quanta7= None,
                ctl_tx_pause_quanta8= None,
                ):
        self.rx_axis_bus = rx_axis_bus
        self.tx_axis_bus = tx_axis_bus
        
        self.tx_ovfout = init_signal(tx_ovfout, 1, 0)
        self.tx_unfout = init_signal(tx_unfout, 1, 0)
        self.stat_rx_aligned = init_signal(stat_rx_aligned, 1, 1)
        
        if gt_txusrclk2 is not None:
            self.clock = Clock(gt_txusrclk2, 4, units="ns")
            cocotb.start_soon(self.clock.start())
            self.dummySink = AxiStreamMonitor(tx_axis_bus, self.clock)
        
class CmacTb:
    def __init__(self, dut):
        self.dut = dut
        self.dev = CmacDevice(
            gt_txusrclk2 = dut.cmac_rxtx_clk,
            rx_axis_bus = AxiStreamBus.from_prefix(dut, "cmac_rx_axis"),
            tx_axis_bus = AxiStreamBus.from_prefix(dut, "cmac_tx_axis"),
            stat_rx_aligned=dut.rx_stat_aligned
        )
        init_signal(dut.tx_stat_rx_aligned, 1, 1)
        
        