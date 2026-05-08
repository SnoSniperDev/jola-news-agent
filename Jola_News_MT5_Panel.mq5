//+------------------------------------------------------------------+
//| Jola_News_MT5_Panel.mq5                                          |
//| Polls the Jola News Agent API and shows a compact panel          |
//| on your MT5 chart — session risk, next event, tweet alert        |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0
#property strict

input string NewsAgentURL     = "https://jola-news-agent.onrender.com/api/mt5";
input int    RefreshMinutes   = 5;     // How often to poll (minutes)
input bool   ShowPanel        = true;
input color  HighColor        = clrTomato;
input color  MedColor         = clrGold;
input color  LowColor         = clrLimeGreen;

string PFX = "JOLA_NEWS_";
datetime g_lastFetch = 0;
int      g_refreshSec;

// Cached data
string g_risk        = "---";
string g_nextEvent   = "---";
string g_nextTime    = "---";
bool   g_tweetAlert  = false;
string g_lastUpdate  = "---";
int    g_highCount   = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "Jola News Panel");
   g_refreshSec = RefreshMinutes * 60;
   if(ShowPanel) InitPanel();
   EventSetTimer(30); // check every 30s if refresh due
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Wipe();
}

void OnTimer()
{
   datetime now = TimeCurrent();
   if(now - g_lastFetch >= g_refreshSec)
   {
      FetchAndUpdate();
      g_lastFetch = now;
   }
}

int OnCalculate(const int rates_total, const int prev_calculated,
   const datetime &time[], const double &open[], const double &high[],
   const double &low[], const double &close[],
   const long &tick_volume[], const long &volume[], const int &spread[])
{
   if(g_lastFetch == 0) FetchAndUpdate();
   if(ShowPanel) UpdatePanel();
   ChartRedraw();
   return rates_total;
}

//+------------------------------------------------------------------+
void FetchAndUpdate()
{
   if(NewsAgentURL == "" || StringFind(NewsAgentURL, "your-") >= 0)
   {
      g_risk = "SET URL IN INPUTS";
      return;
   }

   char   post[], result[];
   string headers;
   int res = WebRequest("GET", NewsAgentURL, "", "", 8000, post, 0, result, headers);

   if(res == -1)
   {
      int err = GetLastError();
      g_risk = "FETCH ERROR " + IntegerToString(err);
      Print("News Agent fetch error: ", err,
            " — Add your Render URL to Tools > Options > Expert Advisors > Allow WebRequest");
      return;
   }

   string json = CharArrayToString(result);
   ParseJSON(json);
}

//+------------------------------------------------------------------+
// Lightweight JSON parser — no external library needed
//+------------------------------------------------------------------+
void ParseJSON(string json)
{
   g_risk       = ExtractStr(json, "session_risk");
   g_highCount  = (int)ExtractNum(json, "high_event_count");
   g_lastUpdate = ExtractStr(json, "last_update");
   g_tweetAlert = StringFind(json, "\"tweet_alert\":true") >= 0;

   // Next event
   int evStart = StringFind(json, "\"next_event\":{");
   if(evStart >= 0)
   {
      string evSub = StringSubstr(json, evStart, 300);
      g_nextEvent = ExtractStr(evSub, "title");
      g_nextTime  = ExtractStr(evSub, "time");
   }
   else
   {
      g_nextEvent = "None scheduled";
      g_nextTime  = "";
   }
}

string ExtractStr(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if(end < 0) return "";
   return StringSubstr(json, pos, end - pos);
}

double ExtractNum(string json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return 0;
   pos += StringLen(search);
   string numStr = StringSubstr(json, pos, 10);
   return StringToDouble(numStr);
}

//+------------------------------------------------------------------+
void InitPanel()
{
   string bg = PFX+"BG";
   if(ObjectFind(0,bg)<0) ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bg,OBJPROP_CORNER,    CORNER_LEFT_LOWER);
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0,bg,OBJPROP_YDISTANCE, 10);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,     310);
   ObjectSetInteger(0,bg,OBJPROP_YSIZE,     130);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,   clrBlack);
   ObjectSetInteger(0,bg,OBJPROP_COLOR,     clrDimGray);
   ObjectSetInteger(0,bg,OBJPROP_WIDTH,     1);
   ObjectSetInteger(0,bg,OBJPROP_BACK,      false);

   PL("HDR",  "JOLA NEWS AGENT",  15, 20, clrGold,   10, CORNER_LEFT_LOWER);
   PL("RISK", "Risk: ---",         15, 40, clrSilver,  9, CORNER_LEFT_LOWER);
   PL("CNT",  "High events: ---", 15, 58, clrSilver,  9, CORNER_LEFT_LOWER);
   PL("EVT",  "Next: ---",         15, 76, clrSilver,  9, CORNER_LEFT_LOWER);
   PL("TWT",  "",                  15, 94, clrTomato,  9, CORNER_LEFT_LOWER);
   PL("UPD",  "Last update: ---", 15,112, clrDimGray,  8, CORNER_LEFT_LOWER);
}

void UpdatePanel()
{
   color riskClr = g_risk=="HIGH" ? HighColor : g_risk=="MEDIUM" ? MedColor : LowColor;
   string evtStr = g_nextEvent == "" ? "None" :
                   (g_nextTime != "" ? g_nextTime + "  " : "") + g_nextEvent;
   if(StringLen(evtStr) > 38) evtStr = StringSubstr(evtStr, 0, 38) + "...";

   string updStr = "---";
   if(StringLen(g_lastUpdate) > 15)
      updStr = StringSubstr(g_lastUpdate, 11, 5) + " UTC";

   SetTxt("RISK", "Session Risk: " + g_risk,       riskClr);
   SetTxt("CNT",  "High impact events: " + IntegerToString(g_highCount), clrWhite);
   SetTxt("EVT",  "Next: " + evtStr,               clrWhite);
   SetTxt("TWT",  g_tweetAlert ? "TRUMP TWEET ALERT — CHECK PHONE" : "", clrTomato);
   SetTxt("UPD",  "Updated: " + updStr,             clrDimGray);
}

void SetTxt(string id, string txt, color clr)
{
   string nm = PFX+"PL_"+id;
   ObjectSetString(0,  nm, OBJPROP_TEXT,  txt);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
}

void PL(string id, string txt, int x, int y, color clr, int fs, ENUM_BASE_CORNER corner)
{
   string nm = PFX+"PL_"+id;
   if(ObjectFind(0,nm)<0) ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,nm,OBJPROP_CORNER,    corner);
   ObjectSetInteger(0,nm,OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0,nm,OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,  fs);
   ObjectSetInteger(0,nm,OBJPROP_COLOR,     clr);
   ObjectSetString(0, nm,OBJPROP_TEXT,      txt);
}

void Wipe()
{
   int n=ObjectsTotal(0);
   for(int i=n-1;i>=0;i--)
   { string nm=ObjectName(0,i); if(StringFind(nm,PFX)==0) ObjectDelete(0,nm); }
}
//+------------------------------------------------------------------+
