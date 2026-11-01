#pragma once
// Common, bounded SD memory snapshot for text and realtime conversation.
// No network, no SD filesystem access and no synchronous semantic lookup here.
// Realtime callers invoke this only during connect/idle refresh.
#include <Arduino.h>
#include "KittyMemory.h"
#include "BrainClock.h"

namespace KittyMemoryContextV6 {
inline String snapshot(size_t factBytes=550, size_t summaryBytes=160,
                       size_t maxBytes=820, bool includeCalendar=true) {
 String text=KittyMemory::factSummary(factBytes);
 String summary=KittyMemory::latestSummaryContext(summaryBytes);
 if(!summary.isEmpty()){
  if(!text.isEmpty())text+='\n';
  text+="recent_summary: "+summary;
 }
 if(includeCalendar){
  String calendar=BrainClock::calendarContext();
  if(!calendar.isEmpty())
   text=calendar+(text.isEmpty()?String(""):String("\n")+text);
 }
 return KittyMemory::clipUTF8(text,maxBytes);
}
} // namespace KittyMemoryContextV6
