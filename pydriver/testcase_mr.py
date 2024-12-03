from driver import *
from utils import *

# Local Looping Settings

MR_TEST_LEN = HUGE_PAGE_BYTE_CNT

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
    

bar_mmap_file = '/dev/bdma_user_mmap0'
huge_mnt_path = '/mnt/hugepages'

driver = BlueRdmaDriver(bar_mmap_file)

buf_controller = HugeMemManager(huge_mnt_path)

user_buf = buf_controller.allocate(MR_TEST_LEN // HUGE_PAGE_BYTE_CNT)
mr_va = get_va_from_mem(user_buf)

driver.memory_register(
    user_buf=user_buf, 
    buf_va=mr_va, 
    length=MR_TEST_LEN,
    key = SEND_SIDE_KEY,
    pd_handle= SEND_SIDE_PD_HANDLER,
    pgt_offset= 0,
    )

driver.create_qp(
    qpn=SEND_SIDE_QPN,
    peer_qpn=RECV_SIDE_QPN,
    pd_handler=SEND_SIDE_PD_HANDLER,
    qp_type=TypeQP.IBV_QPT_RC,
    acc_flag=MemAccessTypeFlag.IBV_ACCESS_LOCAL_WRITE | MemAccessTypeFlag.IBV_ACCESS_REMOTE_READ | MemAccessTypeFlag.IBV_ACCESS_REMOTE_WRITE,
    pmtu=PMTU_VALUE_FOR_TEST,
)

# req_side_offset = 0
# resp_side_offset = MR_TEST_LEN / 2
# req_side_va = mr_va + req_side_offset
# resp_side_va = mr_va + resp_side_offset

# sgl = [
#         SendQueueReqDescFragSGE(
#         F_LKEY=SEND_SIDE_KEY, F_LEN=SEND_BYTE_COUNT, F_LADDR=req_side_va),
#     ]

# driver.send_queue.put_work_request(
#     opcode=WorkReqOpCode.IBV_WR_RDMA_WRITE,
#     is_first=True,
#     is_last=True,
#     sgl=sgl,
#     r_va=resp_side_va,
#     r_key=RECV_SIDE_KEY,
#     r_ip=RECV_SIDE_IP,
#     r_mac=RECE_SIDE_MAC,
#     dqpn=RECV_SIDE_QPN,
#     psn=SEND_SIDE_PSN,
#     pmtu=PMTU_VALUE_FOR_TEST,
#     send_flag=WorkReqSendFlag.IBV_SEND_SIGNALED,
# )

# for idx in range(SEND_BYTE_COUNT):
#     user_buf[req_side_offset + idx] = (0xBB + idx) & 0xFF
#     user_buf[resp_side_offset + idx] = 0
    
# driver.send_queue.sync_pointers()

# report = driver.meta_report_queue.deq_blocking()
# print("receive meta report: ", MeatReportQueueDescBthReth.from_buffer_copy(report))
# assert_descriptor_reth(report, RdmaOpCode.RDMA_WRITE_ONLY)
    
    
# ack_rpt = driver.meta_report_queue.deq_blocking()
# assert_descriptor_ack(ack_rpt)

# src_data = user_buf[req_side_offset + SEND_BYTE_COUNT]
# dst_data = user_buf[resp_side_offset + SEND_BYTE_COUNT]

# if src_data != dst_data:
#     print("Error: DMA Target mem is not the same as source mem")
#     for idx in range(len(src_data)):
#         if src_data[idx] != dst_data[idx]:
#             print("id:", idx,
#                     "src: ", hex(src_data[idx]),
#                     "dst: ", hex(dst_data[idx])
#                     )
#     raise SystemExit
# else:
#     print("PASS")
    
    
driver.stop


