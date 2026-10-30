#pragma once
// Kitty V6 S3 OTA safety helpers. No network server, writes, or automatic flash.
#include <Arduino.h>
#include <esp_ota_ops.h>
#include <esp_partition.h>
#include <esp_app_desc.h>

namespace KittyOTASafety {
struct Status {
 uint32_t runningBytes=0;
 uint32_t nextBytes=0;
 uint8_t runningSubtype=255;
 uint8_t imageState=255;
 bool nextAvailable=false;
 bool rollbackPending=false;
 bool rollbackSupported=false;
};
inline Status inspect(){
 Status s;
 const esp_partition_t *running=esp_ota_get_running_partition();
 const esp_partition_t *next=esp_ota_get_next_update_partition(nullptr);
 if(running){s.runningBytes=running->size;s.runningSubtype=(uint8_t)running->subtype;}
 if(next){s.nextBytes=next->size;s.nextAvailable=true;}
 esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
 if(running && esp_ota_get_state_partition(running,&state)==ESP_OK){
  s.imageState=(uint8_t)state;
  s.rollbackPending=(state==ESP_OTA_IMG_PENDING_VERIFY);
 }
#ifdef CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
 s.rollbackSupported=true;
#endif
 return s;
}
inline bool fitsInactiveSlot(size_t bytes){
 const Status s=inspect();
 return bytes>=1024 && s.nextAvailable && bytes<=s.nextBytes;
}
inline bool confirmRunningImageAfterHealthCheck(bool wifiReady,bool c5Linked,bool memoryReady){
 // Caller must first verify device boot, Wi-Fi, C5 link, and memory worker.
 // Do not mark a partition valid while any health criterion is missing.
 if(!wifiReady||!c5Linked||!memoryReady)return false;
 const Status s=inspect();
 if(!s.rollbackPending)return false;
 return esp_ota_mark_app_valid_cancel_rollback()==ESP_OK;
}
inline bool rollbackUnhealthyImage(){
 // Only effective when the bootloader was compiled with rollback enabled.
 const Status s=inspect();
 if(!s.rollbackPending || !s.rollbackSupported)return false;
 return esp_ota_mark_app_invalid_rollback_and_reboot()==ESP_OK;
}
}
