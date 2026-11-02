#!/usr/bin/env python3
"""Source contract for the S3-only durable, private summary journal."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
memory = (root / "firmware/CuteDisplayBrain/KittyMemory.h").read_text()
worker = (root / "firmware/CuteDisplayBrain/BrainMemoryAI.h").read_text()
realtime = (root / "firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()

def check(condition, message):
    if not condition:
        raise AssertionError(message)

check('SD_MMC.open("/kitty/summary_jobs_v6.tsv",FILE_APPEND)' in memory, "job journal")
check('SD_MMC.open("/kitty/summary_jobs_ack_v6.tsv",FILE_READ)' in memory, "ack recovery")
check('if(!jobs.seek(summaryAckEnd))' in memory, "cursor replay")
check('bool valid=ack.position()==rowStart+line.length()+1' in memory,
      "truncated ACK line cannot advance journal cursor")
check("jobsForAck.read()=='\\n'" in memory,
      "recovered ACK must align with completed journal row")
check('if(!completeRow || a<0' in memory,
      "torn trailing summary job cannot be dispatched")

check('if(xQueueSend(summaryCandidates,&batch,0)==pdTRUE)summaryJobAwaiting=true;' in memory, "in-flight guard")
check('summaryAckEnd=summary.jobEnd;summaryJobAwaiting=false;' in memory, "ack after persistence")
check('savedSummary=expected>0 && written==(size_t)expected;' in memory, "do not ack partially written summary")
check('if(expected>0 && written==(size_t)expected){' in memory, "do not accept partial ack cursor")
check('bool consumed=!summaryJobAwaiting || summary.jobEnd<=summaryAckEnd;' in memory,
      "stale results do not apply storage writes")
check('xQueuePeek(summaryResults,&summary,0)==pdTRUE' in memory,
      "accepted summary retained until durable acknowledgement")
check('(void)xQueueReceive(summaryResults,&summary,0);' in memory and
      'if(consumed){' in memory, "only consume after ack or stale result")
check('savedSummaryJobEnd==summary.jobEnd' in memory,
      "retry ACK without appending duplicate summary")
check('summaryStoreRetryAt=millis()+10000UL;' in memory,
      "SD failures retry with nonbusy backoff")
check('summaryStorePaused=true;' in memory,
      "partial SD writes pause rather than corrupting archive")
check('if(!e.ownerVerified){' in memory, "owner fact write gate")
check('"/kitty/unverified_summaries_v6.tsv"' in memory, "unverified output isolation")
check('if(summary.ownerVerified && !item.isEmpty() && cacheMutex' in memory, "owner context isolation")
check('if(!summarize && cJSON_IsArray(facts)' in worker, "no summary-to-owner-facts promotion")
check('pendingSummaryJobEnd' in worker, "job identity carried across inference")
check('KittyMemory::endConversation();' in realtime, "call boundary")
files = memory.split("static constexpr const char* EXPORT_NAMES[]=", 1)[1].split("};", 1)[0]
check("summary_jobs_v6" not in files and "unverified_summaries_v6" not in files, "journals absent from public sync")

# Ensure journal text includes actual delimiter escapes, not literal backslash sequences.
journal = memory.split("auto submitSummaryBatch=", 1)[1].split("auto dispatchSummaryJob=", 1)[0]
check(r'+"\t"+' in journal and r'+turns+"\n";' in journal, "actual TSV delimiter escapes")
check(r'+"\\t"+' not in journal and r'+turns+"\\n";' not in journal, "double-escaped TSV delimiters")
check('static volatile bool operatorEnabled=true;' in worker, "idle AI automatically enabled")
check('if(running || !operatorEnabled || pausedAfterHttpFailure' in worker, "idle AI enable gate")
check('running=false;requestStartedAt=0;worker=nullptr;' in worker, "worker finishes cleanly")
check('pausedAfterHttpFailure=true;running=false;requestStartedAt=0;worker=nullptr;' in worker, "allocation failure pauses automatic work")
check('static constexpr uint32_t TOTAL_BUDGET_MS=30000UL;' in worker, "cooperative elapsed budget")
check('KittyMemory::clipUTF8(utterance,440)' in worker, "bounded summary prompt")
check('KittyMemory::clipUTF8(utterance,220)' in worker, "bounded fact prompt")
check('cJSON_AddStringToObject(user,"content",inferenceInput.c_str());' in worker, "bounded inference used")
check('[MEMORY AI] result HTTP=' in worker, "non-sensitive successful HTTP parsing diagnostics")
check('[MEMORY AI] interrupted HTTP=' in worker, "non-sensitive cancellation diagnostics")
check('reply.reserve(12288)' in worker, "memory HTTP reply preallocation")
check('e->data_len<=16384' in worker, "memory HTTP reply accepts 8KB responses")
check('response.truncated?1:0' in worker, "memory response truncation diagnostics")
check('truncated=%d format=%d json=%d' in worker, "privacy-safe reply format diagnostics")
check('format==1 && !response.truncated' in worker, "only attempt JSON parsing on complete JSON-like replies")
check('response.truncated?1:0,format,' in worker, "response format printf argument is present")
check('if(format==3 && !response.truncated)' in worker, "streamed response enabled")
check('line.startsWith("data:")' in worker, "SSE data frame detection")
check('cJSON_GetObjectItem(delta,"content")' in worker, "SSE content delta assembly")
check('format==3 && !streamedContent.isEmpty()' in worker, "nonempty complete HTTP SSE content accepted")
check('stream_done=%d stream_chars=%u' in worker, "SSE diagnostics")
check('lastAttempt && (uint32_t)(now-lastAttempt)<RETRY_GAP_MS' in worker, "first automatic summary not delayed by cooldown")
check('cJSON_GetObjectItem(event,"data")' in worker, "SSE Open WebUI wrapper support")
# The model may return more than 220 UTF-8 bytes (especially Japanese).
# Fit only the proposal to the established SD result schema, never raw archives.
check('summaryBytes=summaryText.length();' in worker, "summary byte count is classified")
check('summaryText=KittyMemory::clipUTF8(summaryText,220);' in worker, "UTF-8-safe summary clipping")
check('if((summaryText.isEmpty() || summaryText.length()>=12) && summaryJobEnd)' in worker,
      "short or invalid jobs cannot be acknowledged")
check('KittyMemory::proposeSummary(summaryText,summaryOwnerVerified,summaryConversation,summaryJobEnd)' in worker,
      "validated summary proposal preserves ownership and job identity")
check('summary_stage=%d summary_bytes=%lu clipped=%d output_limit=%d' in worker,
      "privacy-safe summary rejection diagnostics")
check('strcmp(finish->valuestring,"length")==0' in worker,
      "SSE output-token exhaustion is detectable")
check('strcmp(outerFinish->valuestring,"length")==0' in worker,
      "JSON output-token exhaustion is detectable")
check('if(!summarize && cJSON_IsArray(facts)' in worker, "no summary-to-owner fact promotion")

print("Kitty V6 SD summary journal source contract: OK")
