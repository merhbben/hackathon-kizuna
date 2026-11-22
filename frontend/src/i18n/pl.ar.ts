/** المسار: المدخلات ← الموديلات ← الپلان المدروس. */
const plar = {
  title: "كيفاش تحسب الپلان متاعك", sub: "مدخلات أرضك ← موديلات AgroBrain ← الپلان المدروس (أرقام حقيقية متاع الأرض هاذي)",
  inputs: "المدخلات متاعك", fromPlan: "پلان محطوط", fromMap: "رسم على الخريطة", vertices: "زوايا", location: "البلاصة",
  loc_user: "GPS معطى", loc_plan_gps: "GPS مقروء من الپلان", loc_governorate_centroid: "تقريبية (وسط الولاية)", loc_missing: "ناقصة",
  sources: "{{n}} مصدر ماء", quota: "الحصّة", pumps: "المواتير",
  models: "موديلات AgroBrain", climate: "الطقس (NASA POWER، ERA5)", frost: "جليدة ممكنة {{n}} شهور", noFrost: "ما فماش خطر جليدة كبير",
  suitability: "الزراعات اللي تصلح", suitable: "{{n}} زراعات تصلح من {{of}}", excluded: "مستبعدة",
  water: "الماء الموجود", available: "الموجود", quotaShort: "حصّة", pumping: "قدرة الضخّ", needAll: "باش تسقي الأرض الكل يلزم", used: "المستعمل في الپلان",
  optimisation: "التحسين (OR-Tools)", irrigated: "مسقي", rainfed: "بعلي", unused: "موش مزروع", limit: "اللي حاصر",
  lim_quota: "حصّة الماء", lim_water: "ماء شهر {{m}}", lim_land: "مساحة الأرض", lim_budget: "الميزانية", lim_none: "حتى شي",
  partition: "التقسيم (Shapely)", parcels: "{{n}} قطع", infra: "الثنايا والقنوات", nearSources: "الزراعات اللي تشرب برشا قريبة من السوندات",
  irrigEnergy: "السقي والطاقة (FAO-56، CP-SAT)", season: "الموسم", noConflict: "ما فماش تضارب في الموتور", pvReco: "الشمسي المنصوح بيه",
  output: "الپلان المدروس", crops: "{{n}} زراعات", cultivated: "مزروع",
  whyQuota: "الحصّة متاعك {{avail}} م³ في العام تحصر السقي: باش تسقي الأرض الكل يلزم قريب {{need}} م³. AgroBrain يسقي {{irr}} هك، يحط {{rf}} هك بعلي ويخلّي {{un}} هك موش مزروعة. كان تزيد الحصّة ولا مصدر ماء الپلان يتبدّل.",
  whyWater: "الماء الموجود في بعض الشهور ({{avail}} م³ في العام) يحصر السقي: يلزم قريب {{need}} م³. AgroBrain يسقي {{irr}} هك، {{rf}} هك بعلي و{{un}} هك موش مزروعة. دبي ولا كمية أكثر تبدّل الپلان.",
  soilDefault: "افتراضي: SoilGrids ما جاوبش",
  recomputing: "الأرض ولا الموارد تبدّلو: AgroBrain قاعد يعاود يحسب الپلان…",
  stale: "الپلان هذا محسوب بمعطيات قديمة متاع الأرض.",
};
export default plar;
