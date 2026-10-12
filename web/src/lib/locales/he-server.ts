/** Closed UI labels and public status messages supplied by the server. Provider diagnostics remain verbatim. */
export const hebrewServer: Record<string, string> = {
  'Select existing parent recipients': 'יש לבחור הורים שכבר נמצאים ברשימת הנמענים',
  'Unsupported interface language': 'שפת הממשק אינה נתמכת',
  'alerts.recipient_channels': 'ערוצי ההתראות של ההורים',
  'Select an OpenWA sender with an API key.': 'יש לבחור שולח OpenWA עם מפתח API.',
  'Enter a Telegram bot token.': 'יש להזין אסימון לבוט Telegram.',
  'Recipient account was deleted. Remove or replace this recipient explicitly.':
    'חשבון הנמען נמחק. יש להסיר את הנמען או להחליף אותו.',
  'Watch users do not receive parent alerts.': 'משתמשים בתפקיד צפייה אינם מקבלים התראות להורים.',
  'No WhatsApp number. Adding a number is optional; this user cannot receive WhatsApp alerts without one.':
    'לא הוגדר מספר WhatsApp. הוספת מספר היא אופציונלית, אך בלעדיו המשתמש אינו יכול לקבל התראות ב־WhatsApp.',
  'Recipient number is the GreenAPI sender. Use a different personal number.':
    'מספר הנמען הוא מספר השולח של GreenAPI. יש להשתמש במספר אישי אחר.',
  'Recipient number is the OpenWA sender. Use a different personal number.':
    'מספר הנמען הוא מספר השולח של OpenWA. יש להשתמש במספר אישי אחר.',
  'WhatsApp number is not approved. Approve the current number in Users.':
    'מספר WhatsApp לא אושר. יש לאשר את המספר הנוכחי בהגדרות המשתמשים.',
  'No email destination.': 'לא הוגדרה כתובת דוא״ל לנמען.',
  'Email address is not approved. Approve the current email in Users.':
    'כתובת הדוא״ל לא אושרה. יש לאשר אותה בהגדרות המשתמשים.',
  'Email destination does not match an approved user contact.':
    'כתובת הדוא״ל של הנמען אינה תואמת פרטי משתמש שאושרו.',
  "No Telegram chat ID. Start the bot and save the parent's chat ID.":
    'לא הוגדר מזהה שיחת Telegram. יש להפעיל את הבוט ולשמור את מזהה השיחה של ההורה.',
  'No children assigned; alerts are paused for this recipient.':
    'לא שויכו ילדים; ההתראות לנמען זה מושהות.',
  'No WhatsApp number.': 'לא הוגדר מספר WhatsApp.',
  'WhatsApp number is not approved.': 'מספר WhatsApp לא אושר.',
  'No email address.': 'לא הוגדרה כתובת דוא״ל.',
  'Email address is not approved.': 'כתובת הדוא״ל לא אושרה.',
  'Not selected as an alert recipient.': 'המשתמש לא נבחר כנמען להתראות.',
  'Not selected as an alert recipient; add a Telegram destination.':
    'המשתמש לא נבחר כנמען להתראות; יש להוסיף יעד Telegram.',
  'No eligible recipients for {value0}.': 'אין נמענים מתאימים עבור {value0}.',
  'Check destinations and child assignments.': 'יש לבדוק את פרטי הנמענים ואת שיוך הילדים.',
  'Check destinations, approvals and child assignments.':
    'יש לבדוק את פרטי הנמענים, האישורים ואת שיוך הילדים.',
  '{value0} selected recipient(s) cannot receive {value1} alerts.':
    '{value0} נמענים שנבחרו אינם יכולים לקבל התראות באמצעות {value1}.',

  'the edit history': 'היסטוריית העריכות',
  'WhatsApp pairing QR code': 'קוד QR לחיבור WhatsApp',
  'WhatsApp re-pairing QR code': 'קוד QR לחיבור WhatsApp מחדש',
  'this alert': 'התראה זו',
  'user actions': 'פעולות משתמשים',
  'your chats': 'השיחות שלך',
  'the activity chart': 'תרשים הפעילות',
  'chat alert counts': 'מספר ההתראות בשיחות',
  'recent alerts': 'התראות אחרונות',
  'storage usage': 'שימוש באחסון',
  'the database settings': 'הגדרות מסד הנתונים',
  'AI review queue': 'תור הבדיקה של הבינה המלאכותית',
  'the jobs': 'המשימות',
  'learning examples': 'דוגמאות הלמידה',
  'learning comparisons': 'השוואות הלמידה',
  'this conversation': 'שיחה זו',
  'notification settings': 'הגדרות ההתראות',
  'the review queue': 'תור הבדיקה',
  'application schedules': 'תזמוני האפליקציה',

  'Connect OpenWA': 'חיבור OpenWA',
  'Messages cannot be monitored until OpenWA is reachable and a WhatsApp session is connected.':
    'לא ניתן לעקוב אחר הודעות עד ש־OpenWA זמינה וחיבור WhatsApp מחובר.',
  'Configure and test notifications': 'הגדרת התראות ובדיקתן',
  'Parents may not receive alerts until at least one notification provider passes a test.':
    'ייתכן שהורים לא יקבלו התראות עד שלפחות ספק התראות אחד יעבור בדיקה.',
  'Add a parent recipient': 'הוספת נמען הורה',
  'Select at least one parent/admin user with an eligible destination for the active alert channel. GreenAPI and Telegram do not require individual contact approval; OpenWA and email require approval.':
    'בחרו לפחות משתמש הורה או מנהל אחד עם יעד זמין בערוץ שנבחר עבורו. GreenAPI ו־Telegram אינם דורשים אישור פרטני של פרטי קשר; OpenWA ודוא״ל דורשים אישור.',
  'Connect a child phone': 'חיבור טלפון ילד',
  'No child can be monitored until a child phone is connected to OpenWA.':
    'לא ניתן לעקוב אחר ילד עד שטלפון שלו מחובר ל־OpenWA.',
  'Connect and test AI providers': 'חיבור ספקי AI ובדיקתם',
  'Save and test the selected classification and transcription providers. Untested AI connections can leave text, photos or recordings unexamined.':
    'שמרו ובדקו את ספקי הסיווג והתמלול שנבחרו. חיבורי AI שלא נבדקו עלולים להשאיר טקסט, תמונות או הקלטות ללא בדיקה.',
  'Review important defaults': 'בדיקת ברירות מחדל חשובות',
  'Review AI providers, monitoring scope, retention, media storage and notification timing.':
    'בדקו את ספקי ה־AI, היקף המעקב, משך השמירה, אחסון המדיה ותזמון ההתראות.',
  'Ollama classification': 'סיווג Ollama',
  'Ollama image capability': 'תמיכה בתמונות ב־Ollama',
  'OpenAI classification': 'סיווג OpenAI',
  'OpenAI transcription': 'תמלול OpenAI',
  'Local Whisper transcription': 'תמלול Whisper מקומי',
  'Cloudflare transcription': 'תמלול Cloudflare',
  'OpenWA message catch-up': 'השלמת הודעות OpenWA',
  'Apply webhook retry settings and recover missed messages from retained OpenWA history without duplicates.':
    'החלת הגדרות ניסיונות חוזרים ל־webhook ושחזור הודעות שהוחמצו מהיסטוריית OpenWA השמורה ללא כפילויות.',
  'Parent alert responses': 'תגובות להתראות הורים',
  'Check GreenAPI and Telegram review buttons. First accepted response wins; later responses are recorded in notes.':
    'בדיקת כפתורי בדיקה ב־GreenAPI וב־Telegram. התגובה הראשונה שאושרה קובעת; תגובות מאוחרות יותר נרשמות בהערות.',
  'Daily summary': 'סיכום יומי',
  'Daily counts for assigned children, sent to eligible selected parents.':
    'סיכום יומי של מונים לילדים משויכים, הנשלח להורים שנבחרו וזמינים לשליחה.',
  'Device and webhook verification': 'אימות מכשירים ו־webhook',
  'Verify devices and webhooks. Refresh disconnected sessions using the retry policy; notify parents after the configured offline wait.':
    'אימות מכשירים ו־webhook. רענון חיבורים מנותקים בהתאם למדיניות הניסיונות החוזרים; שליחת התראות להורים לאחר זמן ההמתנה שהוגדר לניתוק.',
  'Device failure notifications': 'התראות על כשל מכשירים',
  'Notify selected parents of new incidents, respecting child assignments.':
    'שליחת התראות להורים שנבחרו על אירועים חדשים, בהתאם לשיוך הילדים.',
  'Message and alert retention': 'שמירת הודעות והתראות',
  'Remove expired data. Preserve unresolved reviews and retained alerts.':
    'הסרת מידע שפג תוקפו. בדיקות שלא הושלמו והתראות שמורות נשארות.',
  'Media retention and deletion': 'שמירת מדיה ומחיקתה',
  'Remove expired or explicitly deleted saved media from local or S3 storage.':
    'הסרת מדיה שמורה שפג תוקפה או שסומנה למחיקה, מאחסון מקומי או מ־S3.',
  'Recover stalled jobs': 'שחזור משימות תקועות',
  'Recover expired worker leases so interrupted jobs can continue.':
    'שחזור הקצאות משימות שפג תוקפן כדי שמשימות שנקטעו יוכלו להמשיך.',
  'Pending alert catch-up': 'השלמת התראות ממתינות',
  'Resume held alerts without broadcasting the historical review backlog.':
    'חידוש התראות שעוכבו ללא שליחת פריטי הבדיקה הישנים.',
  'Resolve group names': 'איתור שמות קבוצות',
  'Fetch names for unnamed WhatsApp groups.': 'אחזור שמות לקבוצות WhatsApp ללא שם.',
  'Expired pairing cleanup': 'ניקוי חיבורים שפג תוקפם',
  'Delete abandoned temporary pairings and expired completion receipts.':
    'מחיקת חיבורים זמניים שננטשו ואישורי השלמה שפג תוקפם.',
  'Public URL': 'כתובת ציבורית',
  'Monitor direct chats': 'מעקב אחר שיחות פרטיות',
  'Monitor groups': 'מעקב אחר קבוצות',
  'Monitor outgoing messages': 'מעקב אחר הודעות יוצאות',
  'Message retention (days)': 'משך שמירת הודעות (ימים)',
  'Alert retention (days)': 'משך שמירת התראות (ימים)',
  'Alert timezone': 'אזור הזמן להתראות',
  'Recover missed OpenWA messages': 'שחזור הודעות OpenWA שהוחמצו',
  'Test failed. Check the saved configuration.': 'הבדיקה נכשלה. בדקו את ההגדרות השמורות.',
  'Connection is not ready. Check the configuration and try again.':
    'החיבור אינו מוכן. בדקו את ההגדרות ונסו שוב.',
  'Test passed for saved settings.': 'הבדיקה הצליחה עבור ההגדרות השמורות.',
  'Approval link is invalid or expired. Request a new one.':
    'קישור האישור אינו תקין או שפג תוקפו. בקשו קישור חדש.',
  'Approval link has already been used': 'כבר נעשה שימוש בקישור האישור',
  'Telegram destination changed. Request a new approval link.':
    'יעד Telegram השתנה. בקשו קישור אישור חדש.',
  'This code has expired. Request a new code.': 'תוקף הקוד פג. בקשו קוד חדש.',
  'Invalid verification code': 'קוד האימות אינו תקין',
  'Invalid credentials': 'פרטי הכניסה אינם תקינים',
  Photo: 'תמונה',
  'Voice note': 'הודעה קולית',
  Video: 'וידאו',
  photo: 'תמונה',
  'voice note': 'הודעה קולית',
  'the media': 'המדיה',
  'the message': 'ההודעה',
  'the conversation': 'השיחה',
  'the groups': 'הקבוצות',
  'the chats': 'השיחות',
  'setup reminders': 'תזכורות ההגדרה',
  'setup status': 'מצב ההגדרה',
  'unknown sender': 'שולח לא ידוע',
  processing: 'בעיבוד',
  skipped: 'דולג',
  off: 'כבוי',
  all: 'הכול',
  harmful_review: 'מזיק ודורש בדיקה',
  'Not checked yet. Iris classifies new messages within a few seconds.':
    'טרם נבדק. Iris מסווגת הודעות חדשות בתוך כמה שניות.',
  'The photo kept from this message': 'התמונה שנשמרה מהודעה זו',
}
