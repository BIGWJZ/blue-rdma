import logging

import cocotb
import cocotb.clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb.clock import Clock

from cocotbext.pcie.core import RootComplex
from cocotbext.pcie.xilinx.us import UltraScalePlusPcieDevice
from cocotbext.axi.stream import define_stream
from cocotbext.axi import (AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamMonitor, AxiStreamFrame)

#  class TB architecture
#  ------------------------------------------------------- 
# | Root Complex | <->  | End Pointer |  <->  | Dut(DMAC) |   <->  User Logic     
#  -------------------------------------------------------

BAR0_SIZE = 4 * 1024        # BDMA BAR Space
BAR1_SIZE = 2 * 1024 * 1024 # User BAR Space (Blue-Rdma)

HOST_MEM_SIZE = 64 * 1024 * 1024 # Hosr Memory

DescBus, DescTransaction, DescSource, DescSink, DescMonitor = define_stream("Desc",
    signals=["start_addr", "byte_cnt", "is_write", "valid", "ready"]
)

class PcieTb(object):
    def __init__(self, dut, msix=False):
        self.dut = dut
        self.log = logging.getLogger("Bdma PcieTb")
        self.log.setLevel(logging.DEBUG)
        self.clock = None           # User Clk
        self.resetn = None          # User Rstn
        self.rc = None              # RootComplex
        self.ep = None              # EndPoint
        self.dev = None             # PCI Device of RC
        self.mem = None             # Host Memory
        self.bar_list = []
        
        self._pcie_init(dut, msix)
            
    def _pcie_init(self, dut, msix=False):
        self.clock = dut.CLK
        self.resetn = dut.RST_N
        
        self._bus_width = 512
        self._bus_bytes = 64
        
        # PCIe
        self.rc = RootComplex()

        cq_straddle = False
        cc_straddle = False
        rq_straddle = True
        rc_straddle = True
        rc_4tlp_straddle = False

        self.ep = UltraScalePlusPcieDevice(
            # configuration options
            pcie_generation=3,
            pcie_link_width=16,
            user_clk_frequency=250e6,
            alignment="dword",
            cq_straddle=cq_straddle,
            cc_straddle=cc_straddle,
            rq_straddle=rq_straddle,
            rc_straddle=rc_straddle,
            rc_4tlp_straddle=rc_4tlp_straddle,
            pf_count=1,
            max_payload_size=1024,
            enable_client_tag=True,
            enable_extended_tag=False,
            enable_parity=False,
            enable_rx_msg_interface=False,
            enable_sriov=False,
            enable_extended_configuration=False,

            pf0_msi_enable=True,
            pf0_msi_count=32,
            pf1_msi_enable=False,
            pf1_msi_count=1,
            pf2_msi_enable=False,
            pf2_msi_count=1,
            pf3_msi_enable=False,
            pf3_msi_count=1,
            pf0_msix_enable=msix,
            pf0_msix_table_size=63,
            pf0_msix_table_bir=4,
            pf0_msix_table_offset=0x00000000,
            pf0_msix_pba_bir=4,
            pf0_msix_pba_offset=0x00008000,
            pf1_msix_enable=False,
            pf1_msix_table_size=0,
            pf1_msix_table_bir=0,
            pf1_msix_table_offset=0x00000000,
            pf1_msix_pba_bir=0,
            pf1_msix_pba_offset=0x00000000,
            pf2_msix_enable=False,
            pf2_msix_table_size=0,
            pf2_msix_table_bir=0,
            pf2_msix_table_offset=0x00000000,
            pf2_msix_pba_bir=0,
            pf2_msix_pba_offset=0x00000000,
            pf3_msix_enable=False,
            pf3_msix_table_size=0,
            pf3_msix_table_bir=0,
            pf3_msix_table_offset=0x00000000,
            pf3_msix_pba_bir=0,
            pf3_msix_pba_offset=0x00000000,

            # signals
            user_clk=self.clock,
            # user_reset=~self.resetn,
            user_lnk_up=dut.user_lnk_up,
            # sys_clk=dut.sys_clk,
            # sys_clk_gt=dut.sys_clk_gt,
            # sys_reset=dut.sys_reset,
            # phy_rdy_out=dut.phy_rdy_out,

            rq_bus=AxiStreamBus.from_prefix(dut, "m_axis_rq"),
            pcie_rq_seq_num0=dut.pcie_rq_seq_num0,
            pcie_rq_seq_num_vld0=dut.pcie_rq_seq_num_vld0,
            pcie_rq_seq_num1=dut.pcie_rq_seq_num1,
            pcie_rq_seq_num_vld1=dut.pcie_rq_seq_num_vld1,
            pcie_rq_tag0=dut.pcie_rq_tag0,
            pcie_rq_tag1=dut.pcie_rq_tag1,
            # pcie_rq_tag_av=dut.pcie_rq_tag_av,
            pcie_rq_tag_vld0=dut.pcie_rq_tag_vld0,
            pcie_rq_tag_vld1=dut.pcie_rq_tag_vld1,

            rc_bus=AxiStreamBus.from_prefix(dut, "s_axis_rc"),

            cq_bus=AxiStreamBus.from_prefix(dut, "s_axis_cq"),
            pcie_cq_np_req=dut.pcie_cq_np_req,
            pcie_cq_np_req_count=dut.pcie_cq_np_req_count,

            cc_bus=AxiStreamBus.from_prefix(dut, "m_axis_cc"),

            pcie_tfc_nph_av=dut.pcie_tfc_nph_av,
            pcie_tfc_npd_av=dut.pcie_tfc_npd_av,
            cfg_phy_link_down=dut.cfg_phy_link_down,
            cfg_phy_link_status=dut.cfg_phy_link_status,
            cfg_negotiated_width=dut.cfg_negotiated_width,
            cfg_current_speed=dut.cfg_current_speed,
            cfg_max_payload=dut.cfg_max_payload,
            cfg_max_read_req=dut.cfg_max_read_req,
            cfg_function_status=dut.cfg_function_status,
            cfg_function_power_state=dut.cfg_function_power_state,
            cfg_vf_status=dut.cfg_vf_status,
            cfg_vf_power_state=dut.cfg_vf_power_state,
            cfg_link_power_state=dut.cfg_link_power_state,
            cfg_mgmt_addr=dut.cfg_mgmt_addr,
            cfg_mgmt_function_number=dut.cfg_mgmt_function_number,
            cfg_mgmt_write=dut.cfg_mgmt_write,
            cfg_mgmt_write_data=dut.cfg_mgmt_write_data,
            cfg_mgmt_byte_enable=dut.cfg_mgmt_byte_enable,
            cfg_mgmt_read=dut.cfg_mgmt_read,
            cfg_mgmt_read_data=dut.cfg_mgmt_read_data,
            cfg_mgmt_read_write_done=dut.cfg_mgmt_read_write_done,
            cfg_mgmt_debug_access=dut.cfg_mgmt_debug_access,
            cfg_err_cor_out=dut.cfg_err_cor_out,
            cfg_err_nonfatal_out=dut.cfg_err_nonfatal_out,
            cfg_err_fatal_out=dut.cfg_err_fatal_out,
            cfg_local_error_valid=dut.cfg_local_error_valid,
            cfg_local_error_out=dut.cfg_local_error_out,
            cfg_ltssm_state=dut.cfg_ltssm_state,
            cfg_rx_pm_state=dut.cfg_rx_pm_state,
            cfg_tx_pm_state=dut.cfg_tx_pm_state,
            cfg_rcb_status=dut.cfg_rcb_status,
            cfg_obff_enable=dut.cfg_obff_enable,
            # cfg_pl_status_change=dut.cfg_pl_status_change,
            # cfg_tph_requester_enable=dut.cfg_tph_requester_enable,
            # cfg_tph_st_mode=dut.cfg_tph_st_mode,
            # cfg_vf_tph_requester_enable=dut.cfg_vf_tph_requester_enable,
            # cfg_vf_tph_st_mode=dut.cfg_vf_tph_st_mode,
            cfg_msg_received=dut.cfg_msg_received,
            cfg_msg_received_data=dut.cfg_msg_received_data,
            cfg_msg_received_type=dut.cfg_msg_received_type,
            cfg_msg_transmit=dut.cfg_msg_transmit,
            cfg_msg_transmit_type=dut.cfg_msg_transmit_type,
            cfg_msg_transmit_data=dut.cfg_msg_transmit_data,
            cfg_msg_transmit_done=dut.cfg_msg_transmit_done,
            cfg_fc_ph=dut.cfg_fc_ph,
            cfg_fc_pd=dut.cfg_fc_pd,
            cfg_fc_nph=dut.cfg_fc_nph,
            cfg_fc_npd=dut.cfg_fc_npd,
            cfg_fc_cplh=dut.cfg_fc_cplh,
            cfg_fc_cpld=dut.cfg_fc_cpld,
            cfg_fc_sel=dut.cfg_fc_sel,
            cfg_dsn=dut.cfg_dsn,
            cfg_bus_number=dut.cfg_bus_number,
            cfg_power_state_change_ack=dut.cfg_power_state_change_ack,
            cfg_power_state_change_interrupt=dut.cfg_power_state_change_interrupt,
            cfg_err_cor_in=dut.cfg_err_cor_in,
            cfg_err_uncor_in=dut.cfg_err_uncor_in,
            cfg_flr_in_process=dut.cfg_flr_in_process,
            cfg_flr_done=dut.cfg_flr_done,
            cfg_vf_flr_in_process=dut.cfg_vf_flr_in_process,
            cfg_vf_flr_func_num=dut.cfg_vf_flr_func_num,
            cfg_vf_flr_done=dut.cfg_vf_flr_done,
            cfg_link_training_enable=dut.cfg_link_training_enable,
            cfg_interrupt_int=dut.cfg_interrupt_int,
            cfg_interrupt_pending=dut.cfg_interrupt_pending,
            cfg_interrupt_sent=dut.cfg_interrupt_sent,
            cfg_interrupt_msi_enable=dut.cfg_interrupt_msi_enable,
            cfg_interrupt_msi_mmenable=dut.cfg_interrupt_msi_mmenable,
            cfg_interrupt_msi_mask_update=dut.cfg_interrupt_msi_mask_update,
            cfg_interrupt_msi_data=dut.cfg_interrupt_msi_data,
            cfg_interrupt_msi_select=dut.cfg_interrupt_msi_select,
            cfg_interrupt_msi_int=dut.cfg_interrupt_msi_int,
            cfg_interrupt_msi_pending_status=dut.cfg_interrupt_msi_pending_status,
            cfg_interrupt_msi_pending_status_data_enable=dut.cfg_interrupt_msi_pending_status_data_enable,
            cfg_interrupt_msi_pending_status_function_num=dut.cfg_interrupt_msi_pending_status_function_num,
            cfg_interrupt_msi_sent=dut.cfg_interrupt_msi_sent,
            cfg_interrupt_msi_fail=dut.cfg_interrupt_msi_fail,
            cfg_interrupt_msi_attr=dut.cfg_interrupt_msi_attr,
            cfg_interrupt_msi_tph_present=dut.cfg_interrupt_msi_tph_present,
            cfg_interrupt_msi_tph_type=dut.cfg_interrupt_msi_tph_type,
            cfg_interrupt_msi_tph_st_tag=dut.cfg_interrupt_msi_tph_st_tag,
            cfg_interrupt_msi_function_number=dut.cfg_interrupt_msi_function_number,
            cfg_pm_aspm_l1_entry_reject=dut.cfg_pm_aspm_l1_entry_reject,
            cfg_pm_aspm_tx_l0s_entry_disable=dut.cfg_pm_aspm_tx_l0s_entry_disable,
            cfg_hot_reset_out=dut.cfg_hot_reset_out,
            cfg_config_space_enable=dut.cfg_config_space_enable,
            cfg_req_pm_transition_l23_ready=dut.cfg_req_pm_transition_l23_ready,
            cfg_hot_reset_in=dut.cfg_hot_reset_in,
            cfg_ds_port_number=dut.cfg_ds_port_number,
            cfg_ds_bus_number=dut.cfg_ds_bus_number,
            cfg_ds_device_number=dut.cfg_ds_device_number,
        )

        self._dut_signals_set(dut)
        
        self.ep.log.setLevel(logging.INFO)
        self.ep.functions[0].configure_bar(0, BAR0_SIZE)
        self.ep.functions[0].configure_bar(1, BAR1_SIZE)
        
        self.rc.make_port().connect(self.ep)
        
        self.log.info("Xilinx Us+ PCIe Testbench init done")
    
    def _dut_signals_set(self, dut):
        # reset
        # dut.csrSoftResetSignal.setimmediatevalue(0)
        # dut.global_reset_resetn.setimmediatevalue(1)
        # global_reset_clock = Clock(dut.global_reset_100mhz_clk, 10, units="ns")
        # cocotb.start_soon(global_reset_clock.start())
        # pcie ports
        dut.pcie_cq_np_req.setimmediatevalue(1)
        dut.cfg_mgmt_addr.setimmediatevalue(0)
        dut.cfg_mgmt_function_number.setimmediatevalue(0)
        dut.cfg_mgmt_write.setimmediatevalue(0)
        dut.cfg_mgmt_write_data.setimmediatevalue(0)
        dut.cfg_mgmt_byte_enable.setimmediatevalue(0)
        dut.cfg_mgmt_read.setimmediatevalue(0)
        dut.cfg_mgmt_debug_access.setimmediatevalue(0)
        dut.cfg_msg_transmit.setimmediatevalue(0)
        dut.cfg_msg_transmit_type.setimmediatevalue(0)
        dut.cfg_msg_transmit_data.setimmediatevalue(0)
        dut.cfg_fc_sel.setimmediatevalue(0)
        dut.cfg_dsn.setimmediatevalue(0)
        dut.cfg_power_state_change_ack.setimmediatevalue(0)
        dut.cfg_err_cor_in.setimmediatevalue(0)
        dut.cfg_err_uncor_in.setimmediatevalue(0)
        dut.cfg_flr_done.setimmediatevalue(0)
        dut.cfg_vf_flr_func_num.setimmediatevalue(0)
        dut.cfg_vf_flr_done.setimmediatevalue(0)
        dut.cfg_link_training_enable.setimmediatevalue(1)
        dut.cfg_interrupt_int.setimmediatevalue(0)
        dut.cfg_interrupt_pending.setimmediatevalue(0)
        dut.cfg_interrupt_msi_select.setimmediatevalue(0)
        dut.cfg_interrupt_msi_int.setimmediatevalue(0)
        dut.cfg_interrupt_msi_pending_status.setimmediatevalue(0)
        dut.cfg_interrupt_msi_pending_status_data_enable.setimmediatevalue(0)
        dut.cfg_interrupt_msi_pending_status_function_num.setimmediatevalue(0)       
        dut.cfg_interrupt_msi_attr.setimmediatevalue(0)
        dut.cfg_interrupt_msi_tph_present.setimmediatevalue(0)
        dut.cfg_interrupt_msi_tph_type.setimmediatevalue(0)
        dut.cfg_interrupt_msi_tph_st_tag.setimmediatevalue(0)
        dut.cfg_interrupt_msi_function_number.setimmediatevalue(0)
        dut.cfg_pm_aspm_l1_entry_reject.setimmediatevalue(0)
        dut.cfg_pm_aspm_tx_l0s_entry_disable.setimmediatevalue(0)
        dut.cfg_config_space_enable.setimmediatevalue(1)
        dut.cfg_req_pm_transition_l23_ready.setimmediatevalue(0)
        dut.cfg_hot_reset_in.setimmediatevalue(0)
        dut.cfg_ds_port_number.setimmediatevalue(0)
        dut.cfg_ds_bus_number.setimmediatevalue(0)
        dut.cfg_ds_device_number.setimmediatevalue(0)
        
    async def gen_reset(self):
        self.resetn.value = 0
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.resetn.value = 1
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.log.info("Generated PCIe user_rst")
    
    async def start(self):
        await self.gen_reset()
    
        await self.rc.enumerate()
        self.dev = self.rc.find_device(self.ep.functions[0].pcie_id)
        await self.dev.enable_device()
        await self.dev.set_master()
    
        self.mem = self.rc.mem_pool.alloc_region(HOST_MEM_SIZE) 
        
        self.bar_list.append(self.dev.bar_window[0])
        self.bar_list.append(self.dev.bar_window[1])

    def get_bar(self, bar_idx):
        return PcieBarTb(self.bar_list[bar_idx])
    
    def get_host_mem(self):
        return self.mem
        

class PcieBarTb:
    def __init__(self, bar):
        self.bar = bar
        self.log = logging.getLogger("Bdma PcieBarHost")
        self.log.setLevel(logging.DEBUG)
            
    async def write_csr_blocking(self, addr:int, value:int):
        self.log.debug("PCIeTb Debug: write bar addr:%d, value:%d" % (addr, value))
        await self.bar.write(addr, value.to_bytes(4, byteorder='little', signed=False))  

    async def read_csr_blocking(self, addr) -> int:
        value_bytes = await self.bar.read(addr, 4)
        return int.from_bytes(value_bytes, byteorder='little', signed=False)
    

    