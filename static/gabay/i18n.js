/* LSAMS Gabay App — translations
   Keys mirror data-i18n attributes used in templates.
   Languages: en (English), tl (Tagalog), ceb (Cebuano/Bisaya)
*/
const LSAMS_TRANSLATIONS = {
  en: {
    // nav
    nav_home: 'Home', nav_leads: 'My Leads', nav_checkin: 'Check In',
    nav_history: 'History', nav_me: 'Me',

    // home
    home_greeting_prefix: '',
    home_no_visits: 'No visits yet today. Let\'s get started! 💪',
    home_visits_1: '1 seller visited today. Keep it up!',
    home_visits_many: '{n} sellers visited today. Great work! 🔥',
    home_progress: 'Visited: {done} / {total}',
    home_kpi_leads: 'My Leads', home_kpi_visited: 'Visited Today', home_kpi_live: 'Live',
    home_followups: 'Follow-ups Due Today',
    home_priority: 'Priority Leads',
    home_all_done: 'All caught up!', home_all_done_sub: 'No priority leads right now.',
    home_quick: 'Quick Actions',
    home_checkin_btn: 'Check In Now', home_checkin_sub: 'Log a visit',
    home_leads_btn: 'My Leads',
    home_stalled: '{n} stalled lead(s)!',
    home_stalled_sub: 'No visit in 7+ days.',
    home_stalled_link: 'View now →',
    home_suggest_title: '📍 Suggested Visits',
    home_suggest_sub: 'Best leads to visit today',
    home_traffic_title: 'Traffic Alert',
    home_followup_badge: 'Follow-up',

    // checkin
    checkin_title: 'Check In',
    checkin_sub: 'Log your seller visit',
    checkin_step1: 'Which seller did you visit?',
    checkin_step1_sub: 'Select from your lead list',
    checkin_select_placeholder: '— Select a seller —',
    checkin_step2: 'Where are you now?',
    checkin_step2_sub: 'Tap to get your GPS location',
    checkin_gps_tap: 'Tap for GPS Location',
    checkin_gps_sub: 'Required for check-in',
    checkin_gps_loading: 'Getting location…',
    checkin_gps_loading_sub: 'Please wait, keep screen on',
    checkin_gps_done: 'Location captured!',
    checkin_gps_error: 'Location unavailable',
    checkin_gps_error_sub: 'Enable location in settings and try again',
    checkin_step3: 'What happened?',
    checkin_step3_sub: 'Select the visit outcome',
    outcome_interested: 'Interested',
    outcome_callback: 'Call Back',
    outcome_not_home: 'Not Home',
    outcome_rejected: 'Rejected',
    outcome_registered: 'Registered!',
    outcome_follow_up: 'Follow Up',
    checkin_followup_q: 'When to follow up?',
    checkin_step4: 'Notes',
    checkin_step4_opt: '(Optional)',
    checkin_notes_ph: 'What happened during the visit?',
    checkin_status_label: 'Update Lead Status?',
    checkin_status_opt: '(Optional)',
    checkin_keep_status: '— Keep current status —',
    checkin_status_attempt: 'Attempting',
    checkin_status_nego: 'In Negotiation',
    checkin_status_reg: 'Registration',
    checkin_status_closed: 'Closed (No Sale)',
    checkin_submit: 'Submit Check-In',
    checkin_hint: 'Select seller, location, and outcome to submit',
    checkin_ready: '✅ Ready! Tap the button to save.',

    // profile
    profile_language: 'Language', profile_language_sub: 'Choose your preferred language',
    profile_help: 'Help & Guide',

    // help
    help_home_title: 'Home Screen Guide',
    help_home_body: '<b>My Leads</b> — total sellers assigned to you.<br><b>Visited Today</b> — how many you checked in today.<br><b>Live</b> — sellers already selling on Lazada.<br><br><b>Priority Leads</b> are sellers who need attention. Tap any name to view their details.<br><br><b>Suggested Visits</b> shows the best leads to visit today based on your area and last visits.',
    help_checkin_title: 'How to Check In',
    help_checkin_body: '<b>Step 1</b> — Select the seller you just visited from the list.<br><b>Step 2</b> — Tap the GPS button while standing near the seller\'s location.<br><b>Step 3</b> — Tap what happened during your visit.<br><b>Step 4</b> — Add any notes (optional).<br><br>Tap <b>Submit Check-In</b> when done.',
    help_leads_title: 'My Leads Guide',
    help_leads_body: 'This list shows all sellers assigned to you.<br><br>Use the <b>filter pills</b> at the top to find leads by status.<br>Use the <b>search box</b> to find a seller by name or city.<br><br>Tap any seller to see their full details and visit history.',
    help_close: 'Got it!',
  },

  tl: {
    nav_home: 'Home', nav_leads: 'Mga Lead', nav_checkin: 'Check In',
    nav_history: 'Kasaysayan', nav_me: 'Ako',
    home_no_visits: 'Wala pang bisita ngayon. Halina at magsimula! 💪',
    home_visits_1: '1 seller na ang nabisita mo ngayon. Magaling!',
    home_visits_many: '{n} sellers na ang nabisita mo ngayon. Galing! 🔥',
    home_progress: 'Napuntahan: {done} / {total}',
    home_kpi_leads: 'Aking Leads', home_kpi_visited: 'Nabisita Ngayon', home_kpi_live: 'Live na',
    home_followups: 'Dapat Bisitahin Ngayon',
    home_priority: 'Mga Pinaka-Important na Lead',
    home_all_done: 'Tapos na lahat!', home_all_done_sub: 'Walang priority leads ngayon.',
    home_quick: 'Mabilis na Aksyon',
    home_checkin_btn: 'Mag-Check In', home_checkin_sub: 'I-log ang bisita',
    home_leads_btn: 'Mga Lead Ko',
    home_stalled: '{n} lead ang matagal nang hindi nabibisita!',
    home_stalled_sub: 'Hindi nabisita sa loob ng 7 araw.',
    home_stalled_link: 'Tingnan ngayon →',
    home_suggest_title: '📍 Presuhin Bisitahin',
    home_suggest_sub: 'Pinakamainam na leads ngayon',
    home_traffic_title: 'Babala sa Trapik',
    home_followup_badge: 'Follow-up',
    checkin_title: 'Mag-Check In',
    checkin_sub: 'I-record ang iyong pagbisita sa seller',
    checkin_step1: 'Sino ang binisita mo?', checkin_step1_sub: 'Piliin ang seller',
    checkin_select_placeholder: '— Piliin ang seller —',
    checkin_step2: 'Nasaan ka ngayon?', checkin_step2_sub: 'I-tap para kunin ang lokasyon',
    checkin_gps_tap: 'Pindutin para sa GPS',
    checkin_gps_sub: 'Kailangan para sa check-in',
    checkin_gps_loading: 'Hinahanap ang lokasyon…',
    checkin_gps_loading_sub: 'Sandali lang, huwag patayin ang screen',
    checkin_gps_done: 'Nakuha na ang lokasyon!',
    checkin_gps_error: 'Hindi makuha ang lokasyon',
    checkin_gps_error_sub: 'I-allow ang location sa settings at subukan ulit',
    checkin_step3: 'Ano ang nangyari?', checkin_step3_sub: 'Piliin ang resulta ng bisita',
    outcome_interested: 'Interesado', outcome_callback: 'Tatawag Ulit',
    outcome_not_home: 'Wala sa Bahay', outcome_rejected: 'Ayaw',
    outcome_registered: 'Na-register!', outcome_follow_up: 'Babalik Ulit',
    checkin_followup_q: 'Kailan babalik?',
    checkin_step4: 'Mga Tala', checkin_step4_opt: '(Hindi kailangan)',
    checkin_notes_ph: 'Ano pa ang nangyari?',
    checkin_status_label: 'I-update ang status?', checkin_status_opt: '(Opsyonal)',
    checkin_keep_status: '— Huwag baguhin —',
    checkin_status_attempt: 'Sinusubukan pa', checkin_status_nego: 'Nag-uusap na',
    checkin_status_reg: 'Para sa Registration', checkin_status_closed: 'Hindi matuloy',
    checkin_submit: 'I-submit ang Check-In',
    checkin_hint: 'Piliin ang seller, lokasyon, at resulta para makapag-submit',
    checkin_ready: '✅ Handa na! Pindutin ang button para i-save.',
    profile_language: 'Wika', profile_language_sub: 'Piliin ang iyong wika',
    profile_help: 'Tulong at Gabay',
    help_home_title: 'Gabay sa Home Screen',
    help_home_body: '<b>Aking Leads</b> — kabuuang sellers na itinalaga sa iyo.<br><b>Nabisita Ngayon</b> — ilan na ang binisita mo ngayon.<br><b>Live na</b> — sellers na nagbebenta na sa Lazada.<br><br><b>Pinaka-Important na Lead</b> ay mga sellers na nangangailangan ng pansin. I-tap ang pangalan para makita ang detalye.<br><br><b>Presuhin Bisitahin</b> ay nagpapakita ng pinakamainam na leads batay sa iyong lugar.',
    help_checkin_title: 'Paano Mag-Check In',
    help_checkin_body: '<b>Hakbang 1</b> — Piliin ang seller na binisita mo.<br><b>Hakbang 2</b> — I-tap ang GPS button habang nasa tabi ka ng seller.<br><b>Hakbang 3</b> — I-tap kung ano ang nangyari sa iyong bisita.<br><b>Hakbang 4</b> — Magdagdag ng tala (opsyonal).<br><br>I-tap ang <b>I-submit</b> kapag tapos na.',
    help_leads_title: 'Gabay sa Aking mga Lead',
    help_leads_body: 'Ipinapakita dito ang lahat ng sellers na itinalaga sa iyo.<br><br>Gamitin ang <b>mga pindutan sa taas</b> para mahanap ang leads ayon sa status.<br>Gamitin ang <b>search</b> para mahanap ang seller ayon sa pangalan o lungsod.',
    help_close: 'Naunawaan ko!',
  },

  ceb: {
    nav_home: 'Home', nav_leads: 'Akong Leads', nav_checkin: 'Check In',
    nav_history: 'Kasaysayan', nav_me: 'Ako',
    home_no_visits: 'Wala pay bisita karon. Magsugod na ta! 💪',
    home_visits_1: '1 seller na ang gibisita nimo karon. Maayo!',
    home_visits_many: '{n} sellers na ang gibisita nimo karon. Kabaw! 🔥',
    home_progress: 'Gibisita: {done} / {total}',
    home_kpi_leads: 'Akong Leads', home_kpi_visited: 'Gibisita Karon', home_kpi_live: 'Live na',
    home_followups: 'Kinahanglan Bisitahon Karon',
    home_priority: 'Importante nga Leads',
    home_all_done: 'Natapos na tanan!', home_all_done_sub: 'Walay priority leads karon.',
    home_quick: 'Paspas nga Aksyon',
    home_checkin_btn: 'Mag-Check In', home_checkin_sub: 'I-rekord ang bisita',
    home_leads_btn: 'Akong mga Lead',
    home_stalled: '{n} leads ang dugay nang wala gibisita!',
    home_stalled_sub: 'Wala gibisita sulod sa 7 ka adlaw.',
    home_stalled_link: 'Tan-awa karon →',
    home_suggest_title: '📍 Suhestiyong Bisitahon',
    home_suggest_sub: 'Pinakamaayo nga leads karon',
    home_traffic_title: 'Pasidaan sa Trapiko',
    home_followup_badge: 'Follow-up',
    checkin_title: 'Mag-Check In',
    checkin_sub: 'I-rekord ang imong pagbisita sa seller',
    checkin_step1: 'Kinsa ang gibisita nimo?', checkin_step1_sub: 'Pilia ang seller',
    checkin_select_placeholder: '— Pilia ang seller —',
    checkin_step2: 'Asa ka karon?', checkin_step2_sub: 'I-tap para makuha ang lokasyon',
    checkin_gps_tap: 'Pindota para sa GPS',
    checkin_gps_sub: 'Gikinahanglan para sa check-in',
    checkin_gps_loading: 'Gikuha ang lokasyon…',
    checkin_gps_loading_sub: 'Kadiyot lang',
    checkin_gps_done: 'Nakuha na ang lokasyon!',
    checkin_gps_error: 'Dili makuha ang lokasyon',
    checkin_gps_error_sub: 'I-allow ang location sa settings ug sulayi pag-usab',
    checkin_step3: 'Unsa ang nahitabo?', checkin_step3_sub: 'Pilia ang resulta sa bisita',
    outcome_interested: 'Interesado', outcome_callback: 'Motawag Pag-usab',
    outcome_not_home: 'Wala sa Balay', outcome_rejected: 'Dili Gusto',
    outcome_registered: 'Na-register!', outcome_follow_up: 'Mobalik Pag-usab',
    checkin_followup_q: 'Kanus-a mobalik?',
    checkin_step4: 'Mga Tala', checkin_step4_opt: '(Dili kinahanglan)',
    checkin_notes_ph: 'Unsa pa ang nahitabo?',
    checkin_status_label: 'I-update ang status?', checkin_status_opt: '(Opsyonal)',
    checkin_keep_status: '— Ayaw usba —',
    checkin_status_attempt: 'Gisulayan pa', checkin_status_nego: 'Nagkiestoryahan na',
    checkin_status_reg: 'Para sa Registration', checkin_status_closed: 'Dili matuloy',
    checkin_submit: 'I-submit ang Check-In',
    checkin_hint: 'Pilia ang seller, lokasyon, ug resulta para makapag-submit',
    checkin_ready: '✅ Andam na! Pindota ang button para ma-save.',
    profile_language: 'Pinulongan', profile_language_sub: 'Pilia ang imong sinultihan',
    profile_help: 'Tabang ug Giya',
    help_home_title: 'Giya sa Home Screen',
    help_home_body: '<b>Akong Leads</b> — tanan sellers nga gitudlo kanimo.<br><b>Gibisita Karon</b> — pila na ang gibisita nimo karon.<br><b>Live na</b> — sellers nga nagbaligya na sa Lazada.<br><br><b>Importante nga Leads</b> — mga sellers nga nagkinahanglan og atensyon.',
    help_checkin_title: 'Unsaon Pag-Check In',
    help_checkin_body: '<b>Lakang 1</b> — Pilia ang seller nga gibisita nimo.<br><b>Lakang 2</b> — I-tap ang GPS button samtang duol ka sa seller.<br><b>Lakang 3</b> — I-tap kung unsa ang nahitabo.<br><b>Lakang 4</b> — Magdugang og tala (opsyonal).<br><br>I-tap ang <b>I-submit</b> kung human na.',
    help_leads_title: 'Giya sa Akong mga Lead',
    help_leads_body: 'Kini nagpakita sa tanan sellers nga gitudlo kanimo.<br><br>Gamiton ang mga <b>filter buttons</b> sa ibabaw para pangitaon ang leads pinaagi sa status.',
    help_close: 'Nasabtan ko!',
  }
};

// ── Apply translations ──────────────────────────────────────────────
function getLang() {
  return localStorage.getItem('lsams_lang') || 'en';
}
function setLang(lang) {
  localStorage.setItem('lsams_lang', lang);
  applyTranslations();
}
function t(key, vars) {
  const lang = getLang();
  const dict = LSAMS_TRANSLATIONS[lang] || LSAMS_TRANSLATIONS.en;
  let str = dict[key] || LSAMS_TRANSLATIONS.en[key] || key;
  if (vars) Object.keys(vars).forEach(k => { str = str.replace('{' + k + '}', vars[k]); });
  return str;
}
function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      el.placeholder = val;
    } else if (el.tagName === 'OPTION') {
      el.textContent = val;
    } else {
      el.textContent = val;
    }
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
}
document.addEventListener('DOMContentLoaded', applyTranslations);
