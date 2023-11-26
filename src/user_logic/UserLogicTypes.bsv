
import Settings :: *;
import DataTypes :: *;
import Headers :: *;
import UserLogicSettings :: *;
import ClientServer :: *;

typedef 12 CSR_ADDR_WIDTH;
typedef 4 CSR_DATA_STRB_WIDTH;
typedef TMul#(CSR_DATA_STRB_WIDTH, BYTE_WIDTH) CSR_DATA_WIDTH;
typedef 64 HOST_ADDR_WIDTH;

typedef Bit#(CSR_ADDR_WIDTH) CsrAddr;
typedef Bit#(CSR_DATA_WIDTH) CsrData;


typedef struct {
    t_addr addr;
    t_data data;
} CsrWriteRequest#(type t_addr, type t_data) deriving(Bits);

typedef struct {
    Bit#(0) flag;
} CsrWriteResponse deriving(Bits);

typedef struct {
    t_addr addr;
} CsrReadRequest#(type t_addr) deriving(Bits);

typedef struct {
    t_data data;
} CsrReadResponse#(type t_data) deriving(Bits);



typedef enum {
    RdmaCsrCmdTypeModifyFirstStagePgt = 0,
    RdmaCsrCmdTypeModifySecondStagePgt = 1,
    RdmaCsrCmdTypeMaxGuard = 16'hFFFF // padding to make this enum use 8 bit
} RdmaCsrCmdType deriving(Bits, Eq, FShow);

typedef Bit#(16) ControlCmdReqId;
typedef Bit#(8)  ControlCmdErrCode;

typedef struct {
    RdmaCsrCmdType cmdType;
    ControlCmdReqId reqId;
} RdmaCsrCmdTypeAndId deriving(Bits, FShow);

typedef struct {
    RdmaCsrCmdType cmdType;
    ControlCmdReqId reqId;
    DataStream dataStream;
} DmaFetchedCmd deriving(Bits, FShow);

typedef struct {
    ControlCmdReqId finishedReqId;
    ControlCmdErrCode  errorCode;
} RdmaCmdExecuteResponse deriving(Bits, FShow);

typedef struct {
    Bit#(CSR_DATA_WIDTH) ctlRegCmdSize;
    Bit#(HOST_ADDR_WIDTH) ctlRegCmdAddr;
    RdmaCsrCmdTypeAndId ctlRegCmdTypeAndId;
} RdmaControlCmdEntry deriving(Bits, FShow);

typedef 64 PGT_SECOND_STAGE_ENTRY_REQUEST_SIZE_PADDED;
typedef TDiv#(DATA_BUS_WIDTH, PGT_SECOND_STAGE_ENTRY_REQUEST_SIZE_PADDED) PGT_SECOND_STAGE_ENTRY_REQUEST_PER_STREAM_FRAME;


typedef 12 PAGE_OFFSET_BIT_WIDTH;
typedef TSub#(SizeOf#(ADDR), 1) PAGE_NUMBER_BITS_RANGE_HIGH_POS_4K;
typedef PAGE_OFFSET_BIT_WIDTH PAGE_NUMBER_BITS_RANGE_LOW_POS_4K;
typedef 11 PAGE_OFFSET_BITS_RANGE_HIGH_POS_4K;


typedef UInt#(PAGE_OFFSET_BIT_WIDTH) PageOffset4k;
typedef UInt#(TSub#(SizeOf#(ADDR), PAGE_OFFSET_BIT_WIDTH)) PageNumber4k;


typedef 256 PCIE_MRRS;
typedef PCIE_MRRS RINGBUF_BLOCK_READ_LEN;
typedef TMul#(PCIE_MRRS, BYTE_WIDTH) RINGBUF_READ_BLOCK_BIT_WIDTH;
typedef TLog#(RINGBUF_READ_BLOCK_BIT_WIDTH) RINGBUF_DMA_ACCESS_LEN_WIDTH;
typedef Bit#(RINGBUF_DMA_ACCESS_LEN_WIDTH) RingbufDMABlockAccessLen;
typedef TDiv#(PCIE_MRRS, USER_LOGIC_DESCRIPTOR_BYTE_WIDTH) RINGBUF_DESC_ENTRY_PER_READ_BLOCK;
typedef Bit#(TLog#(RINGBUF_DESC_ENTRY_PER_READ_BLOCK)) RingbufReadBlockInnerOffset;
typedef TLog#(PCIE_MRRS) RINGBUF_READ_BLOCK_BYTE_WIDTH;


typedef Bit#(16) UserLogicDmaLen;

typedef struct {
    ADDR addr;
    UserLogicDmaLen len;
} UserLogicDmaH2cReq deriving(Bits, FShow);

typedef struct {
    DataStream dataStream;
} UserLogicDmaH2cResp deriving(Bits, FShow);


typedef struct {
    ADDR addr;
    UserLogicDmaLen len;
    DataStream dataStream;
} UserLogicDmaC2hReq deriving(Bits, FShow);

typedef struct {
} UserLogicDmaC2hResp deriving(Bits, FShow);


typedef Server#(UserLogicDmaH2cReq, UserLogicDmaH2cResp)    UserLogicDmaReadSrv;
typedef Server#(UserLogicDmaC2hReq, UserLogicDmaC2hResp)    UserLogicDmaWriteSrv;
typedef Client#(UserLogicDmaH2cReq, UserLogicDmaH2cResp)    UserLogicDmaReadClt;
typedef Client#(UserLogicDmaC2hReq, UserLogicDmaC2hResp)    UserLogicDmaWriteClt;

