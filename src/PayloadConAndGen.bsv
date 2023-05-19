import Arbitration :: *;
import BRAMFIFO :: *;
import ClientServer :: *;
import Connectable :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;
import Vector :: *;

import Controller :: *;
import DataTypes :: *;
import PrimUtils :: *;
import Utils :: *;

// interface Server#(type req_type, type resp_type);
//     interface Put#(req_type) request;
//     interface Get#(resp_type) response;
// endinterface: Server

// TODO: add clearAndReset rule
module mkConnectBramQ2PipeOut#(FIFOF#(anytype) bramQ)(
    PipeOut#(anytype)
) provisos(Bits#(anytype, tSz));
    FIFOF#(anytype) postBramQ <- mkFIFOF;
    mkConnection(toPut(postBramQ), toGet(bramQ));
    return convertFifo2PipeOut(postBramQ);
endmodule

// TODO: add clearAndReset rule
module mkConnectPipeOut2BramQ#(
    PipeOut#(anytype) pipeIn, FIFOF#(anytype) bramQ
)(PipeOut#(anytype)) provisos(Bits#(anytype, tSz));
    FIFOF#(anytype) postBramQ <- mkFIFOF;
    mkConnection(toPut(bramQ), toGet(pipeIn));
    mkConnection(toPut(postBramQ), toGet(bramQ));
    return convertFifo2PipeOut(postBramQ);
endmodule

function Bool isDiscardPayload(PayloadConInfo payloadConInfo);
    return case (payloadConInfo) matches
        tagged DiscardPayloadInfo .info: True;
        default                        : False;
    endcase;
endfunction

interface PayloadGenerator;
    interface DataStreamPipeOut payloadDataStreamPipeOut;
    interface PipeOut#(PayloadGenResp) respPipeOut;
endinterface

// If segment payload DataStream, then PayloadGenResp is sent
// at the last fragment of the segmented payload DataStream.
// If not segment, then PayloadGenResp is sent at the first
// fragment of the payload DataStream.
// Flush DMA read responses when error
module mkPayloadGenerator#(
    Controller cntrl,
    DmaReadSrv dmaReadSrv,
    PipeOut#(PayloadGenReq) payloadGenReqPipeIn
)(PayloadGenerator);
    // Output FIFO for PipeOut
    FIFOF#(PayloadGenResp) payloadGenRespQ <- mkFIFOF;

    // Pipeline FIFO
    FIFOF#(Tuple3#(PayloadGenReq, ByteEn, PmtuFragNum)) pendingGenReqQ <- mkFIFOF;
    FIFOF#(Tuple3#(Bool, Bool, PmtuFragNum)) pendingGenRespQ <- mkFIFOF;
    FIFOF#(Tuple3#(DataStream, Bool, Bool)) payloadSegmentQ <- mkFIFOF;
    // TODO: check payloadOutQ buffer size is enough for DMA read delay?
    FIFOF#(DataStream) payloadBufQ <- mkSizedBRAMFIFOF(valueOf(DATA_STREAM_FRAG_BUF_SIZE));
    let payloadBufPipeOut <- mkConnectBramQ2PipeOut(payloadBufQ);

    Reg#(PmtuFragNum) pmtuFragCntReg <- mkRegU;
    Reg#(Bool)     shouldSetFirstReg <- mkReg(False);
    Reg#(Bool)      isFragCntZeroReg <- mkReg(False);
    Reg#(Bool)      isNormalStateReg <- mkReg(True);

    rule clearAndReset if (cntrl.isReset);
        payloadGenRespQ.clear;

        pendingGenReqQ.clear;
        pendingGenRespQ.clear;
        payloadSegmentQ.clear;
        payloadBufQ.clear;

        // if (payloadBufPipeOut.notEmpty) begin
        //     payloadBufPipeOut.deq;
        // end

        shouldSetFirstReg <= False;
        isFragCntZeroReg  <= False;
        isNormalStateReg  <= True;

        // $display("time=%0t: clearAndReset @ mkPayloadGenerator", $time);
    endrule

    rule recvPayloadGenReq if (cntrl.isNonErr && isNormalStateReg);
        let payloadGenReq = payloadGenReqPipeIn.first;
        payloadGenReqPipeIn.deq;
        immAssert(
            !isZero(payloadGenReq.dmaReadReq.len),
            "payloadGenReq.dmaReadReq.len assertion @ mkPayloadGenerator",
            $format(
                "payloadGenReq.dmaReadReq.len=%0d should not be zero",
                payloadGenReq.dmaReadReq.len
            )
        );
        // $display("time=%0t: payloadGenReq=", $time, fshow(payloadGenReq));

        let dmaLen = payloadGenReq.dmaReadReq.len;
        let padCnt = calcPadCnt(dmaLen);
        let lastFragValidByteNum = calcLastFragValidByteNum(dmaLen);
        let lastFragValidByteNumWithPadding = lastFragValidByteNum + zeroExtend(padCnt);
        let lastFragByteEnWithPadding = genByteEn(lastFragValidByteNumWithPadding);
        let pmtuFragNum = calcFragNumByPmtu(payloadGenReq.pmtu);
        immAssert(
            !isZero(lastFragValidByteNumWithPadding),
            "lastFragValidByteNumWithPadding assertion @ mkPayloadGenerator",
            $format(
                "lastFragValidByteNumWithPadding=%0d should not be zero",
                lastFragValidByteNumWithPadding,
                ", dmaLen=%0d, lastFragValidByteNum=%0d, padCnt=%0d",
                dmaLen, lastFragValidByteNum, padCnt
            )
        );

        pendingGenReqQ.enq(tuple3(payloadGenReq, lastFragByteEnWithPadding, pmtuFragNum));
        dmaReadSrv.request.put(payloadGenReq.dmaReadReq);
    endrule

    rule lastFragAddPadding if (cntrl.isNonErr && isNormalStateReg);
        let dmaReadResp <- dmaReadSrv.response.get;
        let { payloadGenReq, lastFragByteEnWithPadding, pmtuFragNum } = pendingGenReqQ.first;

        let curData = dmaReadResp.dataStream;
        let isOrigFirstFrag = curData.isFirst;
        let isOrigLastFrag = curData.isLast;

        if (isOrigLastFrag) begin
            pendingGenReqQ.deq;

            if (payloadGenReq.addPadding) begin
                curData.byteEn = lastFragByteEnWithPadding;
            end
        end

        // TODO: how to notify DmaReadResp error ASAP?
        if (isOrigFirstFrag) begin
            pendingGenRespQ.enq(tuple3(
                payloadGenReq.segment,
                payloadGenReq.addPadding,
                pmtuFragNum
            ));
        end

        payloadSegmentQ.enq(tuple3(curData, dmaReadResp.isRespErr, isOrigLastFrag));
        // $display("time=%0t: generateResp=", $time, fshow(generateResp));
        // if (dmaReadResp.isRespErr) begin
        //     $display(
        //         "time=%0t:", $time, " dmaReadResp.isRespErr=", fshow(dmaReadResp.isRespErr)
        //     );
        // end
    endrule

    rule segmentPayload if (cntrl.isNonErr && isNormalStateReg);
        let { curData, hasDmaRespErr, isOrigLastFrag } = payloadSegmentQ.first;
        payloadSegmentQ.deq;

        let { shouldSegment, addPadding, pmtuFragNum } = pendingGenRespQ.first;
        if (isOrigLastFrag) begin
            pendingGenRespQ.deq;
            // $display(
            //     "time=%0t:", $time, " shouldSegment=", fshow(shouldSegment),
            //     ", pmtuFragNum=%h", pmtuFragNum
            // );
        end

        isNormalStateReg <= !hasDmaRespErr;
        // $display(
        //     "time=%0t:", $time, " isOrigFirstFrag=", fshow(isOrigFirstFrag),
        //     ", isOrigLastFrag=", fshow(isOrigLastFrag),
        //     ", curData.isFirst=", fshow(curData.isFirst),
        //     ", curData.isLast=", fshow(curData.isLast)
        // );

        if (shouldSegment) begin
            if (shouldSetFirstReg || curData.isFirst) begin
                curData.isFirst = True;
                shouldSetFirstReg <= False;

                // let nextPmtuFragCnt = pmtuFragNum - 2;
                pmtuFragCntReg   <= pmtuFragNum - 2;
                isFragCntZeroReg <= isTwo(pmtuFragNum);
            end
            else if (isFragCntZeroReg) begin
                curData.isLast = True;
                shouldSetFirstReg <= True;
            end
            else if (!curData.isLast) begin
                // let nextPmtuFragCnt = pmtuFragCntReg - 1;
                pmtuFragCntReg   <= pmtuFragCntReg - 1;
                isFragCntZeroReg <= isOne(pmtuFragCntReg);
            end
        end

        // Every segmented payload has a payloadGenResp
        // Must send payloadGenResp when curData.isLast,
        // so as to make sure no DMA response error
        if (curData.isLast || hasDmaRespErr) begin
            let payloadGenResp = PayloadGenResp {
                // initiator  : payloadGenReq.initiator,
                addPadding : addPadding,
                segment    : shouldSegment,
                isRespErr  : hasDmaRespErr
            };

            payloadGenRespQ.enq(payloadGenResp);
        end

        payloadBufQ.enq(curData);
    endrule

    rule flushDmaReadResp if (cntrl.isERR || (cntrl.isNonErr && !isNormalStateReg));
        let dmaReadResp <- dmaReadSrv.response.get;
    endrule

    rule flushPayloadGenReqPipeIn if (cntrl.isERR || (cntrl.isNonErr && !isNormalStateReg));
        payloadGenReqPipeIn.deq;
    endrule

    rule flushPipelineQ if (cntrl.isERR || (cntrl.isNonErr && !isNormalStateReg));
        pendingGenReqQ.clear;
        pendingGenRespQ.clear;
        payloadSegmentQ.clear;
    endrule

    rule flushRespQ if (cntrl.isERR);
        // Response related queues cannot be cleared once isNormalStateReg is False,
        // since some payload DataStream in payloadBufQ might be still under processing.
        payloadGenRespQ.clear;
        payloadBufQ.clear;
    endrule

    interface payloadDataStreamPipeOut = payloadBufPipeOut; // convertFifo2PipeOut(payloadBufQ);
    interface respPipeOut = convertFifo2PipeOut(payloadGenRespQ);
endmodule

interface PayloadConsumer;
    interface PipeOut#(PayloadConResp) respPipeOut;
endinterface

// Flush DMA write responses when error
module mkPayloadConsumer#(
    Controller cntrl,
    DataStreamPipeOut payloadPipeIn,
    DmaWriteSrv dmaWriteSrv,
    PipeOut#(PayloadConReq) payloadConReqPipeIn
)(PayloadConsumer);
    // Output FIFO for PipeOut
    FIFOF#(PayloadConResp) consumeRespQ <- mkFIFOF;

    // Pipeline FIFO
    // FIFOF#(Tuple4#(PayloadConReq, PmtuFragNum, Bool, Bool)) consumeReqQ <- mkFIFOF;
    FIFOF#(Tuple2#(PayloadConReq, Bool))              countReqFragQ <- mkFIFOF;
    FIFOF#(Tuple4#(PayloadConReq, Bool, Bool, Bool)) pendingConReqQ <- mkFIFOF;
    FIFOF#(PayloadConReq)                               genConRespQ <- mkFIFOF;
    FIFOF#(Tuple2#(PayloadConReq, DataStream))       pendingDmaReqQ <- mkFIFOF;

    // TODO: check payloadOutQ buffer size is enough for DMA write delay?
    FIFOF#(DataStream) payloadBufQ <- mkSizedBRAMFIFOF(valueOf(DATA_STREAM_FRAG_BUF_SIZE));
    let payloadBufPipeOut <- mkConnectPipeOut2BramQ(payloadPipeIn, payloadBufQ);

    Reg#(PmtuFragNum) remainingFragNumReg <- mkRegU;
    Reg#(Bool)  isRemainingFragNumZeroReg <- mkReg(False);
    Reg#(Bool)       isFirstOrOnlyFragReg <- mkReg(True);
    // Reg#(Bool) busyReg <- mkReg(False);

    rule clearAndReset if (cntrl.isReset);
        consumeRespQ.clear;
        countReqFragQ.clear;
        pendingConReqQ.clear;
        genConRespQ.clear;
        pendingDmaReqQ.clear;
        payloadBufQ.clear;

        // busyReg <= False;
        isFirstOrOnlyFragReg      <= True;
        isRemainingFragNumZeroReg <= False;
        // $display("time=%0t: clearAndReset @ mkPayloadConsumer", $time);
    endrule

    function Action checkIsOnlyPayloadFragment(
        DataStream payload, PayloadConInfo consumeInfo
    );
        action
            immAssert(
                payload.isFirst && payload.isLast,
                "only payload assertion @ mkPayloadConsumer",
                $format(
                    "payload.isFirst=", fshow(payload.isFirst),
                    "and payload.isLast=", fshow(payload.isLast),
                    " should be true when consumeInfo=",
                    fshow(consumeInfo)
                )
            );
        endaction
    endfunction
/*
    function Action sendDmaWriteReqOrDiscard(
        PayloadConReq consumeReq, DataStream payload
    );
        action
            case (consumeReq.consumeInfo) matches
                tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo: begin
                    let dmaWriteReq = DmaWriteReq {
                        metaData  : sendWriteReqReadRespInfo,
                        dataStream: payload
                    };
                    // $display("time=%0t: dmaWriteReq=", $time, fshow(dmaWriteReq));
                    dmaWriteSrv.request.put(dmaWriteReq);
                end
                tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                    // let { atomicRespDmaWriteMetaData, atomicRespPayload } = atomicRespInfo;
                    let dmaWriteReq = DmaWriteReq {
                        metaData   : atomicRespInfo.atomicRespDmaWriteMetaData,
                        dataStream : DataStream {
                            data   : zeroExtendLSB(atomicRespInfo.atomicRespPayload),
                            byteEn : genByteEn(fromInteger(valueOf(ATOMIC_WORK_REQ_LEN))),
                            isFirst: True,
                            isLast : True
                        }
                    };
                    dmaWriteSrv.request.put(dmaWriteReq);
                end
                default: begin
                    immAssert(
                        isDiscardPayload(consumeReq.consumeInfo),
                        "isDiscardPayload assertion @ mkPayloadConsumer",
                        $format(
                            "consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo),
                            " should be DiscardPayload"
                        )
                    );
                end
            endcase
        endaction
    endfunction
*/
    rule recvReq if (cntrl.isNonErr || cntrl.isERR);
        let consumeReq = payloadConReqPipeIn.first;
        payloadConReqPipeIn.deq;

        case (consumeReq.consumeInfo) matches
            tagged DiscardPayloadInfo .discardInfo: begin
                immAssert(
                    !isZero(consumeReq.fragNum),
                    "consumeReq.fragNum assertion @ mkPayloadConsumer",
                    $format(
                        "consumeReq.fragNum=%h should not be zero when consumeInfo is DiscardPayload",
                        consumeReq.fragNum
                    )
                );
            end
            tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                // let { atomicRespDmaWriteMetaData, atomicRespPayload } = atomicRespInfo;
                immAssert(
                    atomicRespInfo.atomicRespDmaWriteMetaData.len == fromInteger(valueOf(ATOMIC_WORK_REQ_LEN)),
                    "atomicRespInfo.atomicRespDmaWriteMetaData.len assertion @ mkPayloadConsumer",
                    $format(
                        "atomicRespDmaWriteMetaData.len=%h should be %h when consumeInfo is AtomicRespInfoAndPayload",
                        atomicRespInfo.atomicRespDmaWriteMetaData.len, valueOf(ATOMIC_WORK_REQ_LEN)
                    )
                );
            end
            tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo    : begin
                immAssert(
                    !isZero(consumeReq.fragNum),
                    "consumeReq.fragNum assertion @ mkPayloadConsumer",
                    $format(
                        "consumeReq.fragNum=%h should not be zero when consumeInfo is SendWriteReqReadRespInfo",
                        consumeReq.fragNum
                    )
                );
            end
            default: begin
                immFail(
                    "unreachible case @ mkPayloadConsumer",
                    $format("consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo))
                );
            end
        endcase

        let isFragNumLessOrEqOne = isLessOrEqOne(consumeReq.fragNum);
        countReqFragQ.enq(tuple2(consumeReq, isFragNumLessOrEqOne));
        // let isFragNumEqTwo       = isTwo(consumeReq.fragNum);
        // let fragNumMinusTwo      = consumeReq.fragNum - 2;
        // consumeReqQ.enq(tuple4(
        //     consumeReq, fragNumMinusTwo, isFragNumLessOrEqOne, isFragNumEqTwo
        // ));
    endrule

    rule countReqFrag if (cntrl.isNonErr || cntrl.isERR);
        let { consumeReq, isFragNumLessOrEqOne } = countReqFragQ.first;

        let isLastReqFrag = isFragNumLessOrEqOne ? True : isRemainingFragNumZeroReg;
        if (isLastReqFrag) begin
            countReqFragQ.deq;
            isFirstOrOnlyFragReg      <= True;
            isRemainingFragNumZeroReg <= False;
        end
        else begin
            if (isFirstOrOnlyFragReg) begin
                remainingFragNumReg       <= consumeReq.fragNum - 2;
                isRemainingFragNumZeroReg <= isTwo(consumeReq.fragNum);
                isFirstOrOnlyFragReg      <= False;
            end
            else begin
                remainingFragNumReg       <= remainingFragNumReg - 1;
                isRemainingFragNumZeroReg <= isOne(remainingFragNumReg);
            end
        end

        pendingConReqQ.enq(tuple4(
            consumeReq, isFragNumLessOrEqOne, isFirstOrOnlyFragReg, isLastReqFrag
        ));
        // $display(
        //     "time=%0t:", $time,
        //     " consumeReq.fragNum=%0d", consumeReq.fragNum,
        //     ", remainingFragNumReg=%0d", remainingFragNumReg,
        //     ", isRemainingFragNumZeroReg=", fshow(isRemainingFragNumZeroReg),
        //     ", isFirstOrOnlyFragReg=", fshow(isFirstOrOnlyFragReg),
        //     ", isLastReqFrag=", fshow(isLastReqFrag)
        // );
    endrule

    rule consumePayload if (cntrl.isNonErr || cntrl.isERR);
        let {
            consumeReq, isFragNumLessOrEqOne, isFirstOrOnlyFrag, isLastReqFrag
        } = pendingConReqQ.first;
        pendingConReqQ.deq;

        case (consumeReq.consumeInfo) matches
            tagged DiscardPayloadInfo .discardInfo: begin
                let payload = payloadBufPipeOut.first;
                payloadBufPipeOut.deq;

                if (isFragNumLessOrEqOne) begin
                    checkIsOnlyPayloadFragment(payload, consumeReq.consumeInfo);
                end

                if (isFirstOrOnlyFrag) begin
                    immAssert(
                        payload.isFirst,
                        "first payload assertion @ mkPayloadConsumer",
                        $format(
                            "payload.isFirst=", fshow(payload.isFirst),
                            " should be true when isFirstOrOnlyFrag=", fshow(isFirstOrOnlyFrag),
                            " and consumeReq=", fshow(consumeReq)
                        )
                    );
                end

                if (isLastReqFrag) begin
                    immAssert(
                        payload.isLast,
                        "last payload assertion @ mkPayloadConsumer",
                        $format(
                            "payload.isLast=", fshow(payload.isLast),
                            " should be true when isLastReqFrag=", fshow(isLastReqFrag),
                            " for discard consumeReq=", fshow(consumeReq.consumeInfo)
                        )
                    );
                end
            end
            tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                genConRespQ.enq(consumeReq);

                immAssert(
                    isFragNumLessOrEqOne && isFirstOrOnlyFrag && isLastReqFrag,
                    "only frag assertion @ mkPayloadConsumer",
                    $format(
                        "isFragNumLessOrEqOne=", fshow(isFragNumLessOrEqOne),
                        ", isFirstOrOnlyFrag=", fshow(isFirstOrOnlyFrag),
                        ", isLastReqFrag=", fshow(isLastReqFrag),
                        " should be all true when atomic consumeReq=",
                        fshow(consumeReq)
                    )
                );

                let payload = dontCareValue;
                pendingDmaReqQ.enq(tuple2(consumeReq, payload));
            end
            tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo: begin
                let payload = payloadBufPipeOut.first;
                payloadBufPipeOut.deq;
                if (isFragNumLessOrEqOne) begin
                    checkIsOnlyPayloadFragment(payload, consumeReq.consumeInfo);
                    // $display(
                    //     "time=%0t: single packet response consumeReq.fragNum=%0d",
                    //     $time, consumeReq.fragNum
                    // );
                end

                if (isFirstOrOnlyFrag) begin
                    immAssert(
                        payload.isFirst,
                        "first payload assertion @ mkPayloadConsumer",
                        $format(
                            "payload.isFirst=", fshow(payload.isFirst),
                            " should be true when isFirstOrOnlyFrag=", fshow(isFirstOrOnlyFrag),
                            " for consumeReq=", fshow(consumeReq)
                        )
                    );
                end

                if (isLastReqFrag) begin
                    immAssert(
                        payload.isLast,
                        "last payload assertion @ mkPayloadConsumer",
                        $format(
                            "payload.isLast=", fshow(payload.isLast),
                            " should be true when isLastReqFrag=", fshow(isLastReqFrag),
                            " for consumeReq=", fshow(consumeReq)
                        )
                    );

                    genConRespQ.enq(consumeReq);
                end
                pendingDmaReqQ.enq(tuple2(consumeReq, payload));
            end
            default: begin
                immFail(
                    "unreachible case @ mkPayloadConsumer",
                    $format("consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo))
                );
            end
        endcase
    endrule
/*
    rule processReq if ((cntrl.isNonErr || cntrl.isERR) && !busyReg);
        let {
            consumeReq, fragNumMinusTwo, isFragNumLessOrEqOne, isFragNumEqTwo
        } = consumeReqQ.first;
        // $display("time=%0t: consumeReq=", $time, fshow(consumeReq));

        // let remainingFragNum       = consumeReq.fragNum - 2;
        // let isRemainingFragNumZero = isZero(remainingFragNum);
        remainingFragNumReg       <= fragNumMinusTwo;
        isRemainingFragNumZeroReg <= isFragNumEqTwo;

        case (consumeReq.consumeInfo) matches
            tagged DiscardPayloadInfo .discardInfo: begin
                let payload = payloadBufPipeOut.first;
                payloadBufPipeOut.deq;

                if (isFragNumLessOrEqOne) begin
                    checkIsOnlyPayloadFragment(payload, consumeReq.consumeInfo);
                    consumeReqQ.deq;
                end
                else begin
                    // remainingFragNumReg       <= remainingFragNum;
                    // isRemainingFragNumZeroReg <= isRemainingFragNumZero;
                    busyReg <= True;
                end
            end
            tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                consumeReqQ.deq;
                pendingConReqQ.enq(consumeReq);
                let payload = dontCareValue;
                pendingDmaReqQ.enq(tuple2(consumeReq, payload));
                // sendDmaWriteReqOrDiscard(consumeReq, payload);
            end
            tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo: begin
                let payload = payloadBufPipeOut.first;
                payloadBufPipeOut.deq;
                if (isFragNumLessOrEqOne) begin
                    checkIsOnlyPayloadFragment(payload, consumeReq.consumeInfo);
                    consumeReqQ.deq;
                    pendingConReqQ.enq(consumeReq);
                    // $display(
                    //     "time=%0t: single packet response consumeReq.fragNum=%0d",
                    //     $time, consumeReq.fragNum
                    // );
                end
                else begin
                    // checkIsFirstPayloadDataStream(payload, consumeReq.consumeInfo);
                    immAssert(
                        payload.isFirst,
                        "only payload assertion @ mkPayloadConsumer",
                        $format(
                            "payload.isFirst=", fshow(payload.isFirst),
                            " should be true when consumeInfo=",
                            fshow(consumeReq.consumeInfo)
                        )
                    );

                    // remainingFragNumReg       <= remainingFragNum;
                    // isRemainingFragNumZeroReg <= isRemainingFragNumZero;
                    busyReg <= True;
                    // $display(
                    //     "time=%0t: multi-packet response remainingFragNumReg=%0d, change to busy",
                    //     $time, consumeReq.fragNum - 1
                    // );
                end
                pendingDmaReqQ.enq(tuple2(consumeReq, payload));
                // sendDmaWriteReqOrDiscard(consumeReq, payload);
            end
            default: begin
                immFail(
                    "unreachible case @ mkPayloadConsumer",
                    $format("consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo))
                );
            end
        endcase
    endrule

    rule consumePayload if ((cntrl.isNonErr || cntrl.isERR) && busyReg);
        let {
            consumeReq, fragNumMinusTwo, isFragNumLessOrEqOne, isFragNumEqTwo
        } = consumeReqQ.first;
        let payload = payloadBufPipeOut.first;
        payloadBufPipeOut.deq;

        // let nextRemainingFragNum   = remainingFragNumReg - 1;
        remainingFragNumReg       <= remainingFragNumReg - 1;
        isRemainingFragNumZeroReg <= isOne(remainingFragNumReg);
        // $display(
        //     "time=%0t:", $time,
        //     " multi-packet response remainingFragNumReg=%0d", remainingFragNumReg,
        //     ", payload.isLast=", fshow(payload.isLast),
        //     ", consumeReq=", fshow(consumeReq)
        // );

        if (isRemainingFragNumZeroReg) begin
            immAssert(
                payload.isLast,
                "payload.isLast assertion @ mkPayloadConsumer",
                $format(
                    "payload.isLast=", fshow(payload.isLast),
                    " should be true when remainingFragNumReg=%h is zero",
                    remainingFragNumReg
                )
            );

            consumeReqQ.deq;
            if (consumeReq.consumeInfo matches tagged SendWriteReqReadRespInfo .info) begin
                // Only non-atomic might have multi-fragment payload data to consume
                pendingConReqQ.enq(consumeReq);
            end
            busyReg <= False;
        end

        pendingDmaReqQ.enq(tuple2(consumeReq, payload));
        // sendDmaWriteReqOrDiscard(consumeReq, payload);
    endrule
*/
    rule issueDmaReq if (cntrl.isNonErr);
        let { consumeReq, payload } = pendingDmaReqQ.first;
        pendingDmaReqQ.deq;

        case (consumeReq.consumeInfo) matches
            tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo: begin
                let dmaWriteReq = DmaWriteReq {
                    metaData  : sendWriteReqReadRespInfo,
                    dataStream: payload
                };
                // $display("time=%0t: dmaWriteReq=", $time, fshow(dmaWriteReq));
                dmaWriteSrv.request.put(dmaWriteReq);
            end
            tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                // let { atomicRespDmaWriteMetaData, atomicRespPayload } = atomicRespInfo;
                let dmaWriteReq = DmaWriteReq {
                    metaData   : atomicRespInfo.atomicRespDmaWriteMetaData,
                    dataStream : DataStream {
                        data   : zeroExtendLSB(atomicRespInfo.atomicRespPayload),
                        byteEn : genByteEn(fromInteger(valueOf(ATOMIC_WORK_REQ_LEN))),
                        isFirst: True,
                        isLast : True
                    }
                };
                dmaWriteSrv.request.put(dmaWriteReq);
            end
            default: begin
                immAssert(
                    isDiscardPayload(consumeReq.consumeInfo),
                    "isDiscardPayload assertion @ mkPayloadConsumer",
                    $format(
                        "consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo),
                        " should be DiscardPayload"
                    )
                );
            end
        endcase
    endrule

    rule genConResp if (cntrl.isNonErr);
        let dmaWriteResp <- dmaWriteSrv.response.get;
        let consumeReq = genConRespQ.first;
        genConRespQ.deq;
        // $display(
        //     "time=%0t: dmaWriteResp=", $time, fshow(dmaWriteResp),
        //     ", consumeReq=", fshow(consumeReq)
        // );

        case (consumeReq.consumeInfo) matches
            tagged SendWriteReqReadRespInfo .sendWriteReqReadRespInfo: begin
                let consumeResp = PayloadConResp {
                    dmaWriteResp : DmaWriteResp {
                        initiator: sendWriteReqReadRespInfo.initiator,
                        isRespErr: dmaWriteResp.isRespErr,
                        sqpn     : sendWriteReqReadRespInfo.sqpn,
                        psn      : sendWriteReqReadRespInfo.psn
                    }
                };
                consumeRespQ.enq(consumeResp);

                immAssert(
                    dmaWriteResp.sqpn == sendWriteReqReadRespInfo.sqpn &&
                    dmaWriteResp.psn  == sendWriteReqReadRespInfo.psn,
                    "dmaWriteResp SQPN and PSN assertion @ mkPayloadConsumer",
                    $format(
                        "dmaWriteResp.sqpn=%h should == sendWriteReqReadRespInfo.sqpn=%h",
                        dmaWriteResp.sqpn, sendWriteReqReadRespInfo.sqpn,
                        ", and dmaWriteResp.psn=%h should == sendWriteReqReadRespInfo.psn=%h",
                        dmaWriteResp.psn, sendWriteReqReadRespInfo.psn
                    )
                );
            end
            tagged AtomicRespInfoAndPayload .atomicRespInfo: begin
                // let { atomicRespDmaWriteMetaData, atomicRespPayload } = atomicRespInfo;
                let consumeResp = PayloadConResp {
                    dmaWriteResp : DmaWriteResp {
                        initiator: atomicRespInfo.atomicRespDmaWriteMetaData.initiator,
                        isRespErr: dmaWriteResp.isRespErr,
                        sqpn     : atomicRespInfo.atomicRespDmaWriteMetaData.sqpn,
                        psn      : atomicRespInfo.atomicRespDmaWriteMetaData.psn
                    }
                };
                // $display("time=%0t: consumeResp=", $time, fshow(consumeResp));
                consumeRespQ.enq(consumeResp);

                immAssert(
                    dmaWriteResp.sqpn == atomicRespInfo.atomicRespDmaWriteMetaData.sqpn &&
                    dmaWriteResp.psn  == atomicRespInfo.atomicRespDmaWriteMetaData.psn,
                    "dmaWriteResp SQPN and PSN assertion @ ",
                    $format(
                        "dmaWriteResp.sqpn=%h should == atomicRespInfo.atomicRespDmaWriteMetaData.sqpn=%h",
                        dmaWriteResp.sqpn, atomicRespInfo.atomicRespDmaWriteMetaData.sqpn,
                        ", and dmaWriteResp.psn=%h should == atomicRespInfo.atomicRespDmaWriteMetaData.psn=%h",
                        dmaWriteResp.psn, atomicRespInfo.atomicRespDmaWriteMetaData.psn
                    )
                );
            end
            default: begin
                immFail(
                    "unreachible case @ mkPayloadConsumer",
                    $format("consumeReq.consumeInfo=", fshow(consumeReq.consumeInfo))
                );
            end
        endcase
    endrule

    // TODO: safe error flush that finish pending requests before flush
    // When error, continue send DMA write requests,
    // so as to flush payload data properly later.
    // But discard DMA write responses when error.
    rule flushDmaWriteResp if (cntrl.isERR);
        let dmaWriteResp <- dmaWriteSrv.response.get;
    endrule

    // rule flushPayloadBufPipeOut if (cntrl.isERR);
    //     payloadBufPipeOut.deq;
    // endrule

    rule flushPipelineQ if (cntrl.isERR);
        payloadBufQ.clear;
        pendingConReqQ.clear;
        pendingDmaReqQ.clear;
    endrule

    rule flushPayloadConResp if (cntrl.isERR);
        consumeRespQ.clear;
    endrule

    interface respPipeOut = convertFifo2PipeOut(consumeRespQ);
endmodule

typedef Server#(AtomicOpReq, AtomicOpResp) AtomicSrv;
// Atomic operation will not generate error
module mkAtomicSrv#(Controller cntrl)(AtomicSrv);
    FIFOF#(AtomicOpReq)   atomicOpReqQ <- mkFIFOF;
    FIFOF#(AtomicOpResp) atomicOpRespQ <- mkFIFOF;

    rule genResp;
        let atomicOpReq = atomicOpReqQ.first;
        atomicOpReqQ.deq;
        // TODO: implement atomic operations
        let atomicOpResp = AtomicOpResp {
            initiator: atomicOpReq.initiator,
            original : atomicOpReq.compData,
            sqpn     : atomicOpReq.sqpn,
            psn      : atomicOpReq.psn
        };
        atomicOpRespQ.enq(atomicOpResp);
    endrule

    return toGPServer(atomicOpReqQ, atomicOpRespQ);
endmodule

interface DmaArbiter4QP;
    interface DmaReadSrv  dmaReadSrv4RQ;
    interface DmaWriteSrv dmaWriteSrv4RQ;
    interface DmaReadSrv  dmaReadSrv4SQ;
    interface DmaWriteSrv dmaWriteSrv4SQ;
endinterface

module mkDmaArbiterInsideQP#(
    DmaReadSrv  dmaReadSrv,
    DmaWriteSrv dmaWriteSrv
)(DmaArbiter4QP);
    FIFOF#(DmaReadReq)     dmaReadReqQ4RQ <- mkFIFOF;
    FIFOF#(DmaReadResp)   dmaReadRespQ4RQ <- mkFIFOF;
    FIFOF#(DmaWriteReq)   dmaWriteReqQ4RQ <- mkFIFOF;
    FIFOF#(DmaWriteResp) dmaWriteRespQ4RQ <- mkFIFOF;

    FIFOF#(DmaReadReq)     dmaReadReqQ4SQ <- mkFIFOF;
    FIFOF#(DmaReadResp)   dmaReadRespQ4SQ <- mkFIFOF;
    FIFOF#(DmaWriteReq)   dmaWriteReqQ4SQ <- mkFIFOF;
    FIFOF#(DmaWriteResp) dmaWriteRespQ4SQ <- mkFIFOF;

    // RQ has higher priority than SQ when issueing DMA requests
    // and receiving DMA responses.
    rule issueDmaReadReq;
        if (dmaReadReqQ4RQ.notEmpty) begin
            let rqDmaReadReq = dmaReadReqQ4RQ.first;
            dmaReadReqQ4RQ.deq;
            dmaReadSrv.request.put(rqDmaReadReq);
        end
        else if (dmaReadReqQ4SQ.notEmpty) begin
            let sqDmaReadReq = dmaReadReqQ4SQ.first;
            dmaReadReqQ4SQ.deq;
            dmaReadSrv.request.put(sqDmaReadReq);
        end
    endrule

    rule issueDmaWriteReq;
        if (dmaWriteReqQ4RQ.notEmpty) begin
            let rqDmaWriteReq = dmaWriteReqQ4RQ.first;
            dmaWriteReqQ4RQ.deq;
            dmaWriteSrv.request.put(rqDmaWriteReq);
        end
        else if (dmaWriteReqQ4SQ.notEmpty) begin
            let sqDmaWriteReq = dmaWriteReqQ4SQ.first;
            dmaWriteReqQ4SQ.deq;
            dmaWriteSrv.request.put(sqDmaWriteReq);
        end
    endrule

    rule recvDmaReadResp;
        let dmaReadResp <- dmaReadSrv.response.get;
        case (dmaReadResp.initiator)
            DMA_INIT_RQ_RD    ,
            DMA_INIT_RQ_WR    ,
            DMA_INIT_RQ_DUP_RD,
            DMA_INIT_RQ_ATOMIC: dmaReadRespQ4RQ.enq(dmaReadResp);
            default           : dmaReadRespQ4SQ.enq(dmaReadResp);
        endcase
    endrule

    rule recvDmaWriteResp;
        let dmaWriteResp <- dmaWriteSrv.response.get;
        case (dmaWriteResp.initiator)
            DMA_INIT_RQ_RD    ,
            DMA_INIT_RQ_WR    ,
            DMA_INIT_RQ_DUP_RD,
            DMA_INIT_RQ_ATOMIC: dmaWriteRespQ4RQ.enq(dmaWriteResp);
            default           : dmaWriteRespQ4SQ.enq(dmaWriteResp);
        endcase
    endrule

    interface dmaReadSrv4RQ  = toGPServer(dmaReadReqQ4RQ,  dmaReadRespQ4RQ);
    interface dmaWriteSrv4RQ = toGPServer(dmaWriteReqQ4RQ, dmaWriteRespQ4RQ);
    interface dmaReadSrv4SQ  = toGPServer(dmaReadReqQ4SQ,  dmaReadRespQ4SQ);
    interface dmaWriteSrv4SQ = toGPServer(dmaWriteReqQ4SQ, dmaWriteRespQ4SQ);
endmodule

typedef Vector#(portSz, DmaReadSrv) DmaReadArbiter#(numeric type portSz);

module mkDmaReadAribter#(DmaReadSrv dmaReadSrv)(DmaReadArbiter#(portSz)) provisos(
    Add#(1, anysize, portSz),
    Add#(TLog#(portSz), 1, TLog#(TAdd#(portSz, 1))) // portSz must be power of 2
);
    function Bool isDmaReadReqLastFrag(DmaReadReq req) = True;
    function Bool isDmaReadRespLastFrag(DmaReadResp resp) = resp.dataStream.isLast;

    DmaReadArbiter#(portSz) arbiter <- mkServerArbiter(
        dmaReadSrv,
        isDmaReadReqLastFrag,
        isDmaReadRespLastFrag
    );
    return arbiter;
endmodule

typedef Vector#(portSz, DmaWriteSrv) DmaWriteArbiter#(numeric type portSz);

module mkDmaWriteAribter#(DmaWriteSrv dmaWriteSrv)(
    DmaWriteArbiter#(portSz)
) provisos(
    Add#(1, anysize, portSz),
    Add#(TLog#(portSz), 1, TLog#(TAdd#(portSz, 1))) // portSz must be power of 2
);
    function Bool isDmaWriteReqLastFrag(DmaWriteReq req) = req.dataStream.isLast;
    function Bool isDmaWriteRespLastFrag(DmaWriteResp resp) = True;

    DmaWriteArbiter#(portSz) arbiter <- mkServerArbiter(
        dmaWriteSrv,
        isDmaWriteReqLastFrag,
        isDmaWriteRespLastFrag
    );
    return arbiter;
endmodule
