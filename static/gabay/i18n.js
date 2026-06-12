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
    help_home_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">📊 Your 3 Key Numbers</div>
  <div style="font-size:13px;line-height:1.7">
    <b>My Leads</b> — all sellers assigned to you<br>
    <b>Visited Today</b> — how many you checked in today<br>
    <b>Live</b> — sellers already selling on Lazada 🎉
  </div>
</div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#E07B00;margin-bottom:6px">⚠️ Stalled Alert</div>
  <div style="font-size:13px;line-height:1.7">If you see a red alert — it means you have leads with <b>no visit in 7+ days</b>. Tap it to see who needs attention immediately.</div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">📍 Priority & Suggested Visits</div>
  <div style="font-size:13px;line-height:1.7">
    <b>Priority Leads</b> — sellers in active negotiation or with a follow-up due today.<br>
    <b>Suggested Visits</b> — the best leads to visit based on your area and how long since last visit. Start here every morning!
  </div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">💡 Tips</div>
  <div style="font-size:13px;line-height:1.7">
    • Aim for at least <b>5 visits per day</b><br>
    • Tap any seller name to see full details<br>
    • Tap your photo to update your profile
  </div>
</div>
</div>`,
    help_checkin_title: 'How to Check In',
    help_checkin_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:8px">4 Steps to Log a Visit</div>
  <div style="font-size:13px;line-height:2">
    <span style="background:#1F3864;color:white;border-radius:50%;width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;margin-right:6px">1</span> <b>Select the seller</b> you visited from your list<br>
    <span style="background:#1F3864;color:white;border-radius:50%;width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;margin-right:6px">2</span> <b>Get GPS</b> — tap the location button while you're there<br>
    <span style="background:#1F3864;color:white;border-radius:50%;width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;margin-right:6px">3</span> <b>Pick the outcome</b> of the visit<br>
    <span style="background:#1F3864;color:white;border-radius:50%;width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;margin-right:6px">4</span> Add notes (optional) → tap <b>Submit</b>
  </div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">✅ Which outcome to choose?</div>
  <div style="font-size:12px;line-height:2">
    <b>Interested</b> — seller wants to know more, not yet registered<br>
    <b>Registered!</b> — seller signed up on Lazada today 🎉<br>
    <b>Call Back</b> — seller said "I'll think about it" or asked you to return<br>
    <b>Follow Up</b> — you promised to return on a specific date<br>
    <b>Not Home</b> — nobody answered, try again later<br>
    <b>Rejected</b> — seller clearly said no
  </div>
</div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#E07B00;margin-bottom:6px">📡 GPS Tip</div>
  <div style="font-size:13px;line-height:1.7">If GPS is slow — step outside or near a window. Make sure Location is turned ON in your phone settings. GPS captures automatically when you open the page!</div>
</div>
<div style="background:#FEF2F2;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#b91c1c;margin-bottom:6px">📵 No Internet?</div>
  <div style="font-size:13px;line-height:1.7">No problem! Your check-in is saved on your phone and <b>automatically sent</b> when you're back online. You'll see a sync notification.</div>
</div>
</div>`,
    help_leads_title: 'My Leads Guide',
    help_leads_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">🔍 Finding Sellers</div>
  <div style="font-size:13px;line-height:1.7">
    Use the <b>filter buttons</b> at the top to show leads by status.<br>
    Use the <b>search box</b> to find a seller by name or city.<br>
    Tap any seller card to see their full details and visit history.
  </div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">🏷️ What the Status Colors Mean</div>
  <div style="font-size:12px;line-height:2.2">
    <span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:8px;font-weight:700">Assigned</span> — just given to you, not visited yet<br>
    <span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:8px;font-weight:700">Attempting</span> — you've visited but seller not yet decided<br>
    <span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:8px;font-weight:700">Negotiation</span> — seller is seriously considering<br>
    <span style="background:#fce7f3;color:#be185d;padding:2px 8px;border-radius:8px;font-weight:700">Registration</span> — seller is in the process of signing up<br>
    <span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:8px;font-weight:700">Live</span> — seller is live on Lazada ✅<br>
    <span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:8px;font-weight:700">Matched</span> — completed, your job is done 🏆
  </div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">💡 Tips for Managing Leads</div>
  <div style="font-size:13px;line-height:1.7">
    • Update the lead <b>status</b> during check-in when something changes<br>
    • Set a <b>follow-up date</b> when the seller asks you to return<br>
    • Sellers in <b>Negotiation</b> need the most attention — visit them often<br>
    • If a seller has been <b>Assigned</b> for 7+ days with no visit, they show as stalled
  </div>
</div>
</div>`,
    help_outcomes_title: 'Visit Outcomes Explained',
    help_outcomes_body: `<div style="display:flex;flex-direction:column;gap:10px;font-size:13px">
<div style="background:#dcfce7;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d">✅ Registered!</div>
  <div style="color:#166534;margin-top:4px">The seller signed up on Lazada during your visit. Best outcome! Update status to Registration or Live.</div>
</div>
<div style="background:#dbeafe;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1d4ed8">🙂 Interested</div>
  <div style="color:#1e40af;margin-top:4px">Seller wants to join but hasn't registered yet. Visit again soon to close it. Update status to Negotiation if they're seriously considering.</div>
</div>
<div style="background:#fef3c7;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#92400e">📞 Call Back</div>
  <div style="color:#78350f;margin-top:4px">Seller said "I'll think about it" or asked you to call again. Set a follow-up date so you don't forget.</div>
</div>
<div style="background:#ede9fe;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#6d28d9">📅 Follow Up</div>
  <div style="color:#5b21b6;margin-top:4px">You agreed to visit again on a specific date. A reminder banner will appear on your home screen on that day.</div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#4a5568">🚪 Not Home</div>
  <div style="color:#4a5568;margin-top:4px">Nobody answered. Try calling first on your next visit. Don't count this as a real visit outcome.</div>
</div>
<div style="background:#fee2e2;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#b91c1c">❌ Rejected</div>
  <div style="color:#991b1b;margin-top:4px">Seller clearly said no. Update status to Closed. You can still try again after a few months if circumstances change.</div>
</div>
</div>`,
    help_batch_title: 'Batch Check-In Guide',
    help_batch_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">What is Batch Check-In?</div>
  <div style="font-size:13px;line-height:1.7">Batch Check-In lets you log <b>multiple sellers at once</b> — perfect when you visit a commercial building or market and speak to several sellers in one trip.</div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">How to Use It</div>
  <div style="font-size:13px;line-height:2">
    <span style="font-weight:800">1.</span> Go to Home → tap <b>Batch Check-In</b><br>
    <span style="font-weight:800">2.</span> Tap the sellers you visited (checkboxes)<br>
    <span style="font-weight:800">3.</span> GPS is captured automatically<br>
    <span style="font-weight:800">4.</span> Choose one outcome that applies to all<br>
    <span style="font-weight:800">5.</span> Add notes → tap Submit
  </div>
</div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#E07B00;margin-bottom:6px">⚠️ When NOT to use Batch</div>
  <div style="font-size:13px;line-height:1.7">If each seller had a very <b>different outcome</b> — use individual check-in for each. Batch works best when you're logging the same type of visit (e.g., all "Not Home" or all "Interested").</div>
</div>
</div>`,
    help_offline_title: 'Offline Mode',
    help_offline_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">📵 Works Without Internet</div>
  <div style="font-size:13px;line-height:1.7">LSAMS works even without signal! Your leads list and the check-in form are available offline. Submitted check-ins are <b>saved on your phone</b> automatically.</div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">🔄 Automatic Sync</div>
  <div style="font-size:13px;line-height:1.7">When your internet comes back, your offline check-ins are sent automatically in the background. You'll see a <b>sync notification</b> confirming it was received.</div>
</div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#E07B00;margin-bottom:6px">📶 Orange bar at the top?</div>
  <div style="font-size:13px;line-height:1.7">That means you're offline right now. Any check-ins you submit will be queued and sent when signal returns. The counter shows how many are pending.</div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">💡 Tips</div>
  <div style="font-size:13px;line-height:1.7">
    • Install the app on your home screen for best offline support<br>
    • Open the app once in the morning while on WiFi to refresh your leads list<br>
    • GPS still works offline — it uses your phone's hardware, not the internet
  </div>
</div>
</div>`,
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
    help_home_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">📊 Ang 3 Pangunahing Numero</div>
  <div style="font-size:13px;line-height:1.7"><b>Aking Leads</b> — lahat ng sellers na itinalaga sa iyo<br><b>Nabisita Ngayon</b> — ilan na ang binisita mo ngayon<br><b>Live</b> — sellers na nagbebenta na sa Lazada 🎉</div>
</div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#E07B00;margin-bottom:6px">⚠️ Babala sa Stalled</div>
  <div style="font-size:13px;line-height:1.7">Kapag nakakita ka ng pulang alerto — may leads kang <b>hindi nabisita ng 7+ araw</b>. I-tap ito para makita kung sino ang nangangailangan ng pansin.</div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">📍 Priority at Suggested Visits</div>
  <div style="font-size:13px;line-height:1.7"><b>Priority Leads</b> — mga sellers na may aktibong negosasyon o follow-up ngayon.<br><b>Suggested Visits</b> — pinakamainam na leads batay sa iyong lugar. Dito magsimula tuwing umaga!</div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">💡 Mga Tips</div>
  <div style="font-size:13px;line-height:1.7">• Target ng hindi bababa sa <b>5 bisita bawat araw</b><br>• I-tap ang pangalan ng seller para makita ang detalye<br>• I-tap ang iyong larawan para i-update ang profile</div>
</div>
</div>`,
    help_checkin_title: 'Paano Mag-Check In',
    help_checkin_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:8px">4 Hakbang para Mag-Log ng Bisita</div>
  <div style="font-size:13px;line-height:2"><b>1.</b> Piliin ang seller na binisita mo<br><b>2.</b> Kunin ang GPS — i-tap ang location button habang nandoon ka<br><b>3.</b> Piliin ang resulta ng bisita<br><b>4.</b> Magdagdag ng tala (opsyonal) → i-tap ang <b>Submit</b></div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">✅ Aling Outcome ang Pipiliin?</div>
  <div style="font-size:12px;line-height:2.2"><b>Interesado</b> — gusto ng seller pero hindi pa nag-register<br><b>Na-register!</b> — nag-sign up ang seller ngayon 🎉<br><b>Tatawag Ulit</b> — sinabi niyang "mag-iisip muna"<br><b>Babalik Ulit</b> — nag-usap na kayo ng petsa ng susunod na pagbalik<br><b>Wala sa Bahay</b> — walang sumagot, subukan ulit<br><b>Ayaw</b> — malinaw na tumanggi ang seller</div>
</div>
<div style="background:#FEF2F2;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#b91c1c;margin-bottom:6px">📵 Walang Internet?</div>
  <div style="font-size:13px;line-height:1.7">Walang problema! Ise-save ang iyong check-in sa telepono at <b>awtomatikong ipapadala</b> kapag bumalik ang koneksyon.</div>
</div>
</div>`,
    help_leads_title: 'Gabay sa Aking mga Lead',
    help_leads_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">🔍 Paghahanap ng Sellers</div>
  <div style="font-size:13px;line-height:1.7">Gamitin ang <b>mga filter buttons</b> sa taas para ipakita ang leads ayon sa status.<br>Gamitin ang <b>search box</b> para hanapin ang seller ayon sa pangalan o lungsod.</div>
</div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#1F3864;margin-bottom:6px">🏷️ Kahulugan ng mga Status Color</div>
  <div style="font-size:12px;line-height:2.2">
    <span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:8px;font-weight:700">Assigned</span> — bagong itinalaga, hindi pa nabibisita<br>
    <span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:8px;font-weight:700">Attempting</span> — nabisita mo na pero hindi pa nagpasya<br>
    <span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:8px;font-weight:700">Negotiation</span> — sineseryoso nang pag-isipan ng seller<br>
    <span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:8px;font-weight:700">Live</span> — live na ang seller sa Lazada ✅<br>
    <span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:8px;font-weight:700">Matched</span> — tapos na, ikaw ay nagtagumpay 🏆
  </div>
</div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px">
  <div style="font-weight:800;color:#15803d;margin-bottom:6px">💡 Mga Tips</div>
  <div style="font-size:13px;line-height:1.7">• I-update ang <b>status</b> tuwing may pagbabago sa check-in<br>• Mag-set ng <b>follow-up date</b> kapag humingi ng oras ang seller<br>• Ang mga seller sa <b>Negotiation</b> ang pinaka-nangangailangan ng madalas na pagbisita</div>
</div>
</div>`,
    help_outcomes_title: 'Paliwanag ng mga Outcome',
    help_outcomes_body: `<div style="display:flex;flex-direction:column;gap:10px;font-size:13px">
<div style="background:#dcfce7;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d">✅ Na-register!</div><div style="color:#166534;margin-top:4px">Nag-sign up ang seller sa Lazada. Pinakamainam na resulta!</div></div>
<div style="background:#dbeafe;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1d4ed8">🙂 Interesado</div><div style="color:#1e40af;margin-top:4px">Gustong sumali pero hindi pa nag-register. Bisitahin muli para masara.</div></div>
<div style="background:#fef3c7;border-radius:10px;padding:12px"><div style="font-weight:800;color:#92400e">📞 Tatawag Ulit</div><div style="color:#78350f;margin-top:4px">Sinabi niyang "mag-iisip muna". Mag-set ng follow-up date.</div></div>
<div style="background:#ede9fe;border-radius:10px;padding:12px"><div style="font-weight:800;color:#6d28d9">📅 Babalik Ulit</div><div style="color:#5b21b6;margin-top:4px">Nag-usap kayo ng petsa ng susunod na pagbisita. Lilitaw ang reminder sa home screen.</div></div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px"><div style="font-weight:800;color:#4a5568">🚪 Wala sa Bahay</div><div style="color:#4a5568;margin-top:4px">Walang sumagot. Subukang tumawag muna bago bumalik.</div></div>
<div style="background:#fee2e2;border-radius:10px;padding:12px"><div style="font-weight:800;color:#b91c1c">❌ Ayaw</div><div style="color:#991b1b;margin-top:4px">Malinaw na tumanggi ang seller. I-update ang status sa Closed.</div></div>
</div>`,
    help_batch_title: 'Gabay sa Batch Check-In',
    help_batch_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">Ano ang Batch Check-In?</div><div style="font-size:13px;line-height:1.7">Pwede kang mag-log ng <b>maraming sellers nang sabay-sabay</b> — mainam kapag bumisita ka sa isang gusali o palengke at nakausap mo ang maraming sellers sa isang pagkakataon.</div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">Paano Gamitin</div><div style="font-size:13px;line-height:2"><b>1.</b> Home → i-tap ang <b>Batch Check-In</b><br><b>2.</b> Piliin ang mga seller na binisita mo<br><b>3.</b> Awtomatikong kukuha ng GPS<br><b>4.</b> Pumili ng isang outcome para sa lahat<br><b>5.</b> Magdagdag ng tala → i-submit</div></div>
</div>`,
    help_offline_title: 'Offline Mode',
    help_offline_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">📵 Gumagana Kahit Walang Internet</div><div style="font-size:13px;line-height:1.7">Gumagana ang LSAMS kahit walang signal! Ang iyong listahan ng leads at check-in form ay available offline.</div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">🔄 Awtomatikong Sync</div><div style="font-size:13px;line-height:1.7">Kapag bumalik ang internet, awtomatikong ipapadala ang iyong offline check-ins. Makakakita ka ng <b>sync notification</b> na nagpapatunay na natanggap na ito.</div></div>
</div>`,
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
    help_home_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">📊 Ang 3 Importante nga Numero</div><div style="font-size:13px;line-height:1.7"><b>Akong Leads</b> — tanan sellers nga gitudlo kanimo<br><b>Gibisita Karon</b> — pila na ang gibisita nimo karon<br><b>Live</b> — sellers nga nagbaligya na sa Lazada 🎉</div></div>
<div style="background:#FFF7ED;border-radius:10px;padding:12px"><div style="font-weight:800;color:#E07B00;margin-bottom:6px">⚠️ Stalled Alert</div><div style="font-size:13px;line-height:1.7">Kung makakita kag pula nga alerto — may leads kang <b>wala gibisita sulod sa 7+ ka adlaw</b>. I-tap para makita kung kinsa ang nagkinahanglan og atensyon.</div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">📍 Priority ug Suggested Visits</div><div style="font-size:13px;line-height:1.7"><b>Priority Leads</b> — mga sellers nga adunay aktibong negosasyon o follow-up karon.<br><b>Suggested Visits</b> — pinakamaayo nga leads base sa imong lugar. Diri magsugod matag buntag!</div></div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">💡 Tips</div><div style="font-size:13px;line-height:1.7">• Target og labing menos <b>5 bisita matag adlaw</b><br>• I-tap ang ngalan sa seller para makita ang detalye<br>• I-tap ang imong litrato para i-update ang profile</div></div>
</div>`,
    help_checkin_title: 'Unsaon Pag-Check In',
    help_checkin_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:8px">4 ka Lakang para Mag-log og Bisita</div><div style="font-size:13px;line-height:2"><b>1.</b> Pilia ang seller nga gibisita nimo<br><b>2.</b> Kuha og GPS — i-tap ang location button samtang naa ka didto<br><b>3.</b> Pilia ang resulta sa bisita<br><b>4.</b> Magdugang og tala (opsyonal) → i-tap ang <b>Submit</b></div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">✅ Unsang Outcome ang Pilion?</div><div style="font-size:12px;line-height:2.2"><b>Interesado</b> — gusto mosali pero wala pa mag-register<br><b>Na-register!</b> — nag-sign up ang seller karon 🎉<br><b>Motawag Pag-usab</b> — miingon og "mag-hunahuna pa ko"<br><b>Mobalik Pag-usab</b> — nagkasabutan og adlaw sa sunod nga pagbalik<br><b>Wala sa Balay</b> — walay mitubag, sulayi pag-usab<br><b>Dili Gusto</b> — klaro nga mibalibad ang seller</div></div>
<div style="background:#FEF2F2;border-radius:10px;padding:12px"><div style="font-weight:800;color:#b91c1c;margin-bottom:6px">📵 Walay Internet?</div><div style="font-size:13px;line-height:1.7">Walay problema! Maluwas ang imong check-in sa telepono ug <b>awtomatikong ipadala</b> kung mobalik na ang koneksyon.</div></div>
</div>`,
    help_leads_title: 'Giya sa Akong mga Lead',
    help_leads_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">🔍 Pagpangita og Sellers</div><div style="font-size:13px;line-height:1.7">Gamiton ang <b>mga filter buttons</b> sa ibabaw para ipakita ang leads base sa status.<br>Gamiton ang <b>search box</b> para pangitaon ang seller pinaagi sa ngalan o lungsod.</div></div>
<div style="background:#F8FAFD;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">🏷️ Unsa ang Kahulogan sa mga Status Color</div><div style="font-size:12px;line-height:2.2">
<span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:8px;font-weight:700">Assigned</span> — bag-ong gitudlo, wala pa gibisita<br>
<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:8px;font-weight:700">Attempting</span> — gibisita na pero wala pa nagpasya<br>
<span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:8px;font-weight:700">Negotiation</span> — seryoso nang gihunahuna sa seller<br>
<span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:8px;font-weight:700">Live</span> — live na ang seller sa Lazada ✅<br>
<span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:8px;font-weight:700">Matched</span> — nahuman na, nagmadaog ka 🏆
</div></div>
</div>`,
    help_outcomes_title: 'Pasiuna sa mga Outcome',
    help_outcomes_body: `<div style="display:flex;flex-direction:column;gap:10px;font-size:13px">
<div style="background:#dcfce7;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d">✅ Na-register!</div><div style="color:#166534;margin-top:4px">Nag-sign up ang seller sa Lazada. Pinakamaayo nga resulta!</div></div>
<div style="background:#dbeafe;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1d4ed8">🙂 Interesado</div><div style="color:#1e40af;margin-top:4px">Gusto mosali pero wala pa mag-register. Bisitaha pag-usab para masirhan.</div></div>
<div style="background:#fef3c7;border-radius:10px;padding:12px"><div style="font-weight:800;color:#92400e">📞 Motawag Pag-usab</div><div style="color:#78350f;margin-top:4px">Miingon og "mag-hunahuna pa ko". Mag-set og follow-up date.</div></div>
<div style="background:#fee2e2;border-radius:10px;padding:12px"><div style="font-weight:800;color:#b91c1c">❌ Dili Gusto</div><div style="color:#991b1b;margin-top:4px">Klaro nga mibalibad ang seller. I-update ang status sa Closed.</div></div>
</div>`,
    help_batch_title: 'Giya sa Batch Check-In',
    help_batch_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">Unsa ang Batch Check-In?</div><div style="font-size:13px;line-height:1.7">Pwede kang mag-log og <b>daghang sellers sa usa ka higayon</b> — perpekto kung mibisita ka sa usa ka building o merkado ug nakiestorya ka sa daghang sellers.</div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">Unsaon Gamiton</div><div style="font-size:13px;line-height:2"><b>1.</b> Home → i-tap ang <b>Batch Check-In</b><br><b>2.</b> Pilia ang mga seller nga gibisita nimo<br><b>3.</b> Awtomatiko ang GPS<br><b>4.</b> Pili og usa ka outcome para sa tanan<br><b>5.</b> Magdugang og tala → i-submit</div></div>
</div>`,
    help_offline_title: 'Offline Mode',
    help_offline_body: `<div style="display:flex;flex-direction:column;gap:14px">
<div style="background:#EEF2FF;border-radius:10px;padding:12px"><div style="font-weight:800;color:#1F3864;margin-bottom:6px">📵 Molihok Bisan Walay Internet</div><div style="font-size:13px;line-height:1.7">Molihok ang LSAMS bisan walay signal! Ang imong listahan sa leads ug ang check-in form mahimong gamiton offline.</div></div>
<div style="background:#F0FDF4;border-radius:10px;padding:12px"><div style="font-weight:800;color:#15803d;margin-bottom:6px">🔄 Awtomatikong Sync</div><div style="font-size:13px;line-height:1.7">Kung mobalik na ang internet, awtomatiko rang ipadala ang imong offline check-ins. Makakita kag <b>sync notification</b> nga nagkumpirma niini.</div></div>
</div>`,
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
