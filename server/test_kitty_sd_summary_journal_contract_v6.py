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
check('if(xQueueSend(summaryCandidates,&batch,0)==pdTRUE)summaryJobAwaiting=true;' in memory, "in-flight guard")
check('summaryAckEnd=summary.jobEnd;summaryJobAwaiting=false;' in memory, "ack after persistence")
check('summaryJobAwaiting && summary.jobEnd>summaryAckEnd' in memory, "no stale ack")
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
check('static volatile bool operatorEnabled=false;' in worker, "idle AI defaults off")
check('if(running || !operatorEnabled || pausedAfterHttpFailure' in worker, "idle AI enable gate")
check('operatorEnabled=false;\n    running=false;requestStartedAt=0;' in worker, "one request per opt-in")
check('operatorEnabled=false;running=false;requestStartedAt=0;worker=nullptr;' in worker, "allocation failure clears opt-in")
check('static constexpr uint32_t TOTAL_BUDGET_MS=30000UL;' in worker, "cooperative elapsed budget")
check('KittyMemory::clipUTF8(utterance,440)' in worker, "bounded summary prompt")
check('KittyMemory::clipUTF8(utterance,220)' in worker, "bounded fact prompt")
check('cJSON_AddStringToObject(user,"content",inferenceInput.c_str());' in worker, "bounded inference used")
check('[MEMORY AI] result HTTP=' in worker, "non-sensitive successful HTTP parsing diagnostics")
check('[MEMORY AI] interrupted HTTP=' in worker, "non-sensitive cancellation diagnostics")
check('reply.reserve(12288)' in worker, "memory HTTP reply preallocation")
check('e->data_len<=16384' in worker, "memory HTTP reply accepts 8KB responses")
check('response.truncated?1:0' in worker, "memory response truncation diagnostics")
print("Kitty V6 SD summary journal source contract: OK")
