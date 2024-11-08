import FIFOF :: *;
import SpecialFIFOs :: *;
import ClientServer :: * ;
import GetPut :: *;
import Clocks :: * ;
import Vector :: *;
import BRAM :: *;

import UserLogicSettings :: *;
import UserLogicTypes :: *;
import RdmaUtils :: *;

import DmaWrapper::*;
import PcieTypes::*;
import DmaTypes::*;

interface BdmaWrapper;
    interface UserLogicDmaReadWideSrv dmaReadSrv;
    interface UserLogicDmaWriteWideSrv dmaWriteSrv;
    interface Client#(CsrReadRequest#(CsrAddr), CsrReadResponse#(CsrData)) csrReadClt;
    interface Client#(CsrWriteRequest#(CsrAddr, CsrData), CsrWriteResponse) csrWriteClt; 

    // Raw PCIe interfaces, connected to the Xilinx PCIe IP
    (* prefix = "" *)interface RawXilinxPcieIp       rawPcie;
endinterface

(* synthesize *)
module mkBdmaWrapper(BdmaWrapper);
    BdmaControllerBypassWrapper#(CSR_ADDR_WIDTH, CSR_DATA_WIDTH) bdmac <- mkBdmaControllerBypassWrapper;
    
    interface UserLogicDmaReadWideSrv dmaReadSrv;
        interface Put request;
            method Action put(UserLogicDmaH2cReq rdReq);
                bdmac.c2hRdSrvA.request.put(BdmaUserC2hRdReq{
                    addr: rdReq.addr,
                    len : zeroExtend(rdReq.len)
                });
            endmethod
        endinterface

        interface Get response;
            method ActionValue#(UserLogicDmaH2cWideResp) get;
                let resp <- bdmac.c2hRdSrvA.response.get;
                return UserLogicDmaH2cWideResp {
                    dataStream: unpack(pack(resp.dataStream))
                };
            endmethod
        endinterface
    endinterface

    interface UserLogicDmaWriteWideSrv dmaWriteSrv;
        interface Put request;
            method Action put(UserLogicDmaC2hWideReq wrReq);
                bdmac.c2hWrSrvA.request.put(BdmaUserC2hWrReq{
                    addr: wrReq.addr,
                    len : zeroExtend(wrReq.len),
                    dataStream: unpack(pack(wrReq.dataStream))
                });
            endmethod
        endinterface

        interface Get response;
            method ActionValue#(UserLogicDmaC2hResp) get;
                let resp <- bdmac.c2hWrSrvA.response.get;
                return UserLogicDmaC2hResp{};
            endmethod
        endinterface
    endinterface

    interface Client csrReadClt;
        interface Get request;
            method ActionValue#(CsrReadRequest#(CsrAddr)) get;
                let req <- bdmac.csrRdClt.request.get;
                return unpack(pack(req));
            endmethod
        endinterface

        interface Put response;
            method Action put(CsrReadResponse#(CsrData) resp);
                bdmac.csrRdClt.response.put(unpack(pack(resp)));
            endmethod
        endinterface
    endinterface

    interface Client csrWriteClt;
        interface Get request;
            method ActionValue#(CsrWriteRequest#(CsrAddr, CsrData)) get;
                let req <- bdmac.csrWrClt.request.get;
                return unpack(pack(req));
            endmethod
        endinterface

        interface Put response;
            method Action put(CsrWriteResponse resp);
                bdmac.csrWrClt.response.put(unpack(pack(resp)));
            endmethod
        endinterface
    endinterface

    interface rawPcie     = bdmac.rawPcie;
endmodule