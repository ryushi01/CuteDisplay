"""Static S3 receipt/ACK integration safety invariants; no physical device.

This is source-only compatibility testing. Hardware still runs the previous
validated firmware; the live Open WebUI gateway has no matching capabilities.
"""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
S3 = (ROOT / "firmware/CuteDisplayBrain/KittyMemory.h").read_text()
CALL = (ROOT / "firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()
SYNC = (ROOT / "firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
S3_PART = (ROOT / "firmware/CuteDisplayBrain/KittyMemoryContextV6.h").read_text()


class OwnerSdArchiveHandoffContract(unittest.TestCase):
    def test_receipt_is_optional_tenth_snapshot_file(self):
        start = S3.index("static constexpr const char* EXPORT_NAMES[]")
        names = S3[start:S3.index(";", start)]
        self.assertEqual(names.count(".tsv"), 9)
        self.assertIn('"shareable_memories_v6.tsv"', names)
        self.assertIn('"owner_turn_receipts_v6.tsv"', names)
        self.assertIn("uint32_t boundaries[10]", S3)
        self.assertIn("uint32_t frozen[KittyMemory::EXPORT_COUNT]", SYNC)
        self.assertIn("ownerReceiptRevision", SYNC)
        self.assertIn("receiptsBefore!=KittyMemory::ownerReceiptRevision", SYNC)
        self.assertIn("startReceipts", SYNC)
        self.assertIn("syncedReceipts=startReceipts", SYNC)

    def test_receipt_syntax_is_bounded_and_only_sd_worker_persists(self):
        self.assertIn('row.startsWith("owner-v1\\t")', S3)
        self.assertIn("row[row.length()-1]!='\\n'", S3)
        self.assertIn("if(tabs!=10)return false", S3)
        self.assertIn("row.length()>OWNER_RECEIPT_LINE_MAX", S3)
        self.assertIn("OWNER_RECEIPT_MAX_FILE", S3)
        self.assertIn('SD_MMC.open("/kitty/owner_turn_receipts_v6.tsv",FILE_APPEND)', S3)
        self.assertIn("xQueueReceive(ownerReceiptWrites,ownerReceiptScratch,0)", S3)
        self.assertIn("out.flush()", S3)
        self.assertIn("ownerReceiptRevision++", S3)
        self.assertIn("heap_caps_malloc(2*sizeof(OwnerReceiptWrite),MALLOC_CAP_SPIRAM", S3)
        self.assertIn("ownerReceiptIngress=(OwnerReceiptWrite*)heap_caps_calloc", S3)
        # No receipt signing or private trust keys on the device.
        self.assertNotIn("KITTY_OWNER_ARCHIVE_RECEIPT_SECRET_HEX", S3)
        self.assertNotIn("issue_owner_receipt", S3)

    def test_real_archive_offset_and_exact_bytes_are_verified_before_ack(self):
        self.assertIn("e.archiveEpoch==ownerArchiveEpoch", S3)
        self.assertIn("e.conversation==activeConversation", S3)
        self.assertIn('SD_MMC.open("/kitty/conversations.tsv",FILE_READ)', S3)
        self.assertIn("if(check.read()!=(uint8_t)raw[k])", S3)
        self.assertIn("raw.length()==written", S3)
        self.assertIn("mbedtls_sha256(", S3)
        self.assertIn("xQueueSend(archiveAcks,&ack,0)", S3)
        self.assertIn("archiveAcks)xQueueReset(archiveAcks)", S3)

    def test_gateway_opt_in_only_never_blocks_audio_on_unsupported_gateway(self):
        self.assertIn("static bool ownerArchiveSupported=false;", CALL)
        self.assertIn('strcmp(type,"kitty.memory.owner_archive.capabilities")==0', CALL)
        self.assertIn("ownerArchiveSupported=ready && cJSON_IsTrue(flag);", CALL)
        self.assertIn('strcmp(type,"kitty.memory.owner_archive.receipt")==0', CALL)
        self.assertIn("ownerArchiveSupported && ready", CALL)
        self.assertIn('cJSON_AddStringToObject(msg,"type","kitty.memory.owner_archive.ack")', CALL)
        self.assertIn("if(!sendEvent(msg)){", CALL)
        self.assertIn("ownerArchiveSupported=false;KittyMemory::setOwnerArchiveEnabled(false);", CALL)
        self.assertIn("if(ownerArchiveSupported && ready){", CALL)
        self.assertNotIn('cJSON_AddBoolToObject(auth,"kitty_owner_archive_ack",true)', CALL)
        self.assertIn("KittyMemory::queueOpaqueOwnerReceipt", CALL)
        self.assertNotIn("KittyMemory::queueOpaqueOwnerReceipt", S3_PART)

    def test_candidate_speaker_remains_unverified_and_owner_fact_path_untouched(self):
        self.assertIn("uint8_t ownerVerified=0", S3)
        self.assertIn("// Voice matching is probabilistic: NEVER set ownerVerified from a match.", S3)
        self.assertIn("if(!e.ownerVerified){", S3)
        self.assertIn("t.item);", CALL)
        self.assertIn("speaker,source,item);", CALL)
        self.assertNotIn("e.ownerVerified=1", S3)
        self.assertNotIn("ownerVerified=true", CALL)
        self.assertIn('strcmp(type,"kitty.memory.owner_archive.receipt")==0', CALL)


if __name__ == "__main__":
    unittest.main()
