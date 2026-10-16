/** Hebrew text for additional controls without dotted translation keys. */
import { language } from './language'

const text: Record<string, string> = {
  'your phones': 'הטלפונים שלך',
  'the settings': 'ההגדרות',
  'Worth a look': 'כדאי לבדוק',
  file: 'קובץ',
  files: 'קבצים',
  ' and ': ' ו־',
  '{n} messages Iris could not classify': '{n} הודעות שאיריס לא הצליחה לסווג',
  '{n} alerts not delivered to your WhatsApp': '{n} התראות שלא נשלחו ל־WhatsApp שלך',
  '{n} phones with no messages in the configured window': '{n} טלפונים ללא הודעות בפרק הזמן שהוגדר',
  '{n} phones that have never received messages': '{n} טלפונים שמעולם לא התקבלו מהם הודעות',
  '{parts} need your attention': '{parts} דורשות תשומת לב',
  'Iris checked {n} messages today and did not flag harmful content.':
    'איריס בדקה {n} הודעות היום ולא סימנה תוכן פוגעני.',
  'Phone connections': 'חיבורי טלפונים',
  Users: 'משתמשים',
  Classifications: 'סיווגים',
  'Message receipts': 'אישורי הודעות',
  'Stored media': 'מדיה שמורה',
  System: 'מערכת',
  Light: 'בהיר',
  Dark: 'כהה',
  'Account and appearance': 'חשבון ומראה',
  Appearance: 'מראה',
  'Sign out': 'התנתקות',
  Watch: 'מעקב',
  Manage: 'ניהול',
  More: 'עוד',
  Main: 'ניווט ראשי',
  'A new alert needs you': 'יש התראה חדשה',
  Open: 'פתיחה',
  'Skip to content': 'מעבר לתוכן',
  'Edited, show the edit history': 'נערכה, הצגת היסטוריית העריכה',
  'Edit history': 'היסטוריית עריכה',
  'Every wording of this message Iris saw, newest first.':
    'כל נוסח של ההודעה הזו שאיריס ראתה, מהחדש לישן.',
  Original: 'מקורי',
  'Earlier version': 'גרסה קודמת',
  'The content is withheld, so no earlier wording is kept.': 'התוכן הוסתר, כך שאין נוסח קודם שמור.',
  'No earlier wording was kept for this message.': 'לא נשמר נוסח קודם להודעה הזו.',
  'Clear filters': 'ניקוי סינונים',
  Filters: 'סינונים',
  'Narrow the list.': 'צמצום הרשימה.',
  'Show results': 'הצגת תוצאות',
  'Not checked yet. Iris classifies new messages within a few seconds.':
    'עדיין לא נבדקה. איריס מסווגת הודעות חדשות תוך כמה שניות.',
  Dismissed: 'נדחתה',
  Seen: 'נצפתה',
  'New messages and alerts appear on their own': 'הודעות והתראות חדשות מופיעות מעצמן',
  'Trying to reconnect': 'מנסה להתחבר מחדש',
  Live: 'בזמן אמת',
  'Reconnecting…': 'מתחבר/ת מחדש…',
  'Try again': 'ניסיון נוסף',
  'Show chart': 'הצגת תרשים',
  'Show as table': 'הצגה כטבלה',
  'The photo kept from this message': 'התמונה שנשמרה מההודעה הזו',
  'Cooldown per chat': 'תקופת צינון לכל צ׳אט',
  'Messages of context': 'הודעות הקשר',
  'Context goes back': 'ההקשר חוזר אחורה',
  'Keep messages for': 'שמירת הודעות למשך',
  'Keep alerts for': 'שמירת התראות למשך',
  'Keep media for': 'שמירת מדיה למשך',
  'Kept media is being deleted.': 'המדיה השמורה נמחקת.',
  'Could not delete the media.': 'לא ניתן היה למחוק את המדיה.',
  'Kept now': 'שמור כעת',
  'Files stay until their keep time ends, even if you turn keeping off.':
    'קבצים נשארים עד שזמן השמירה שלהם מסתיים, גם אם תכבה/י את השמירה.',
  'Delete all kept media?': 'למחוק את כל המדיה השמורה?',
  'Every kept photo and voice note is deleted from the storage. The messages and alerts stay.':
    'כל תמונה והודעה קולית שנשמרו יימחקו מהאחסון. ההודעות וההתראות יישארו.',
  'Delete media': 'מחיקת המדיה',
  'A score at or above the harmful level is flagged. Between the two levels Iris is unsure: it':
    'ציון שמגיע לרמת "מזיק" או מעליה מסומן כהתראה. בין שתי הרמות איריס אינה בטוחה: היא בודקת שוב עם ההקשר של הצ׳אט סביב ההודעה, ואז מבקשת ממך לבדוק אם זה עדיין לא ברור.',
  'The new passwords do not match.': 'הסיסמאות החדשות אינן תואמות.',
  'Password changed. Any other signed-in sessions were signed out.':
    'הסיסמה שונתה. כל שאר ההפעלות המחוברות נותקו.',
  'Could not change the password. Try again.': 'לא ניתן היה לשנות את הסיסמה. נסה/י שוב.',
  'On this browser': 'בדפדפן הזה',
  'Stored content (message text, alert quotes, kept photos and voice notes) is hidden until you press the eye. This applies to this browser only.':
    'תוכן שמור (טקסט הודעות, ציטוטים מהתראות, תמונות והודעות קוליות שנשמרו) מוסתר עד שתלחצ/י על העין. זה חל על הדפדפן הזה בלבד.',
  'Show content by default': 'הצגת תוכן כברירת מחדל',
  'Everything starts shown, and you can still hide it with the eye. Leave it off on a shared screen.':
    'הכול מוצג כברירת מחדל, ועדיין אפשר להסתיר עם העין. השאר/י את זה כבוי במסך משותף.',
  'Change password': 'שינוי סיסמה',
  'Use at least 8 characters. Changing it signs out every other browser.':
    'יש להשתמש בלפחות 8 תווים. שינוי הסיסמה מנתק את כל הדפדפנים האחרים.',
  'Current password': 'סיסמה נוכחית',
  'New password (at least 8 characters)': 'סיסמה חדשה (לפחות 8 תווים)',
  'Repeat new password': 'חזרה על הסיסמה החדשה',
  'Settings saved.': 'ההגדרות נשמרו.',
  'Thresholds must be numbers from 0 to 1, with "needs a look" lower than "harmful".':
    'הספים חייבים להיות מספרים בין 0 ל-1, כאשר "כדאי לבדוק" נמוך מ"מזיק".',
  Settings: 'הגדרות',
  'Providers, how Iris judges messages, where alerts go, and how long things are kept.':
    'ספקים, איך איריס שופטת הודעות, לאן ההתראות נשלחות וכמה זמן הדברים נשמרים.',
  'Settings sections': 'אזורי ההגדרות',
  OpenAI: 'OpenAI',
  'Checks every message for harm. The moderation endpoint is free.':
    'בודקת כל הודעה לאיתור נזק. נקודת הקצה לבדיקת תוכן היא חינמית.',
  'API key': 'מפתח API',
  'Voice and video': 'קול ווידאו',
  'Turns audio into text so it can be checked like any message.':
    'הופכת שמע לטקסט כדי שניתן יהיה לבדוק אותו כמו כל הודעה.',
  Provider: 'ספק',
  'OpenAI model': 'מודל של OpenAI',
  'Cloudflare account ID': 'מזהה חשבון Cloudflare',
  'Cloudflare API token': 'אסימון API של Cloudflare',
  Model: 'מודל',
  Moderation: 'בדיקת תוכן',
  'How much of the chat Iris reads around a message it is unsure about.':
    'כמה מהצ׳אט איריס קוראת סביב הודעה שהיא לא בטוחה לגביה.',
  'Moderation model': 'מודל בדיקת התוכן',
  'Messages of context (1 to 20)': 'הודעות הקשר (1 עד 20)',
  'Context goes back (hours)': 'ההקשר חוזר אחורה (שעות)',
  Thresholds: 'ספי סיווג',
  'Scores are 0 to 1. Lower numbers make Iris more cautious.':
    'הציונים הם בין 0 ל-1. מספרים נמוכים יותר הופכים את איריס לזהירה יותר.',
  'Where alerts go': 'לאן ההתראות נשלחות',
  'Iris sends each alert as a WhatsApp message from one of your phones to your own number.':
    'איריס שולחת כל התראה כהודעת וואטסאפ מאחד הטלפונים שלך למספר שלך עצמך.',
  'Send alerts from': 'שליחת התראות מ',
  'Recipient (phone number in international format, or a chat ID)':
    'נמען (מספר טלפון בפורמט בינלאומי, או מזהה צ׳אט)',
  'Frequency and timing': 'תדירות ותזמון',
  'Cooldown per chat (minutes)': 'תקופת צינון לכל צ׳אט (דקות)',
  'Time zone': 'אזור זמן',
  'Also alert on items needing review': 'התרעה גם על פריטים שדורשים בדיקה',
  'Off by default: those wait in the Review page instead.':
    'כבוי כברירת מחדל: אלה ממתינים בעמוד הבדיקה במקום זאת.',
  'Tell me when an alerted message is edited or deleted':
    'הודעה לי כשהודעה שהתריעו עליה נערכת או נמחקת',
  'Sends a short follow-up on WhatsApp. It never repeats the message.':
    'שולחת הודעת המשך קצרה בוואטסאפ. היא לעולם לא חוזרת על ההודעה המקורית.',
  'What to watch': 'מה לעקוב אחריו',
  'Turn off anything you do not want Iris to check.': 'כבה/י כל דבר שאת/ה לא רוצה שאיריס תבדוק.',
  'Messages the child sends': 'הודעות שהילד/ה שולח/ת',
  'Direct chats': 'שיחות ישירות',
  Groups: 'קבוצות',
  'How long to keep things': 'כמה זמן לשמור דברים',
  'Messages tied to an alert are kept until that alert expires. Kept media has its own limit under Media.':
    'הודעות המשויכות להתראה נשמרות עד שתוקף ההתראה פג. למדיה שנשמרת יש מגבלה משלה תחת מדיה.',
  'Keep messages for (days)': 'שמירת הודעות למשך (ימים)',
  'Keep alerts for (days)': 'שמירת התראות למשך (ימים)',
  'Keep media': 'שמירת מדיה',
  'By default Iris deletes every photo and voice note as soon as it has been checked. Turn this on to keep copies you can open from alerts.':
    'כברירת מחדל איריס מוחקת כל תמונה והודעה קולית מיד לאחר שנבדקה. הפעל/י את זה כדי לשמור עותקים שניתן לפתוח מהתראות.',
  'Files can only be opened after you sign in to Iris.': 'ניתן לפתוח קבצים רק אחרי כניסה לאיריס.',
  'Only what Iris judges harmful': 'רק מה שאיריס שופטת כמזיק',
  'The media behind your alerts.': 'המדיה שמאחורי ההתראות שלך.',
  'Harmful and needs a look': 'מזיק וגם כדאי לבדוק',
  'Also the items waiting in the review queue.': 'גם הפריטים הממתינים בתור הבדיקה.',
  Everything: 'הכול',
  'Every photo and voice note. Uses the most space.': 'כל תמונה והודעה קולית. תופס הכי הרבה מקום.',
  'Content Iris withholds (anything sexual involving minors, or sexual images) is never':
    'תוכן שאיריס חוסמת (כל דבר מיני שמערב קטינים, או תמונות מיניות) לעולם לא נשמר, לא משנה מה תבחר/י. וידאו לא נשמר בכלל, כי איריס בודקת מה הווידאו אומר, לא מה הוא מציג.',
  'Works with Cloudflare R2, AWS S3, SeaweedFS, MinIO and other S3-compatible':
    'עובד עם Cloudflare R2,‏ AWS S3,‏ SeaweedFS,‏ MinIO ושירותים תואמי S3 נוספים. יש ליצור את ה-bucket קודם.',
  Endpoint: 'כתובת (Endpoint)',
  'For example https://ACCOUNT.r2.cloudflarestorage.com, https://s3.eu-west-1.amazonaws.com or http://seaweed.lan:8333':
    'לדוגמה https://ACCOUNT.r2.cloudflarestorage.com,‏ https://s3.eu-west-1.amazonaws.com או http://seaweed.lan:8333',
  Bucket: 'שם ה-Bucket',
  Region: 'אזור (Region)',
  'Use auto for Cloudflare R2.': 'יש להשתמש ב-auto עבור Cloudflare R2.',
  'Access key ID': 'מזהה מפתח גישה (Access Key ID)',
  'Secret access key': 'מפתח גישה סודי (Secret Access Key)',
  'Folder in the bucket': 'תיקייה בתוך ה-Bucket',
  'Optional. Everything is kept under it.': 'רשות. הכול נשמר תחתיה.',
  'Path-style addresses': 'כתובות בסגנון Path-style',
  'Keep this on for R2, SeaweedFS and MinIO. Turn it off for AWS S3 buckets that need bucket.host addresses.':
    'השאר/י את זה פעיל עבור R2,‏ SeaweedFS ו-MinIO. כבה/י את זה עבור מכלי האחסון של AWS S3 שזקוקות לכתובות מהצורה bucket.host.',
  'Test storage': 'בדיקת האחסון',
  'How long to keep it': 'כמה זמן לשמור אותה',
  'Keep media for (days)': 'שמירת מדיה למשך (ימים)',
  'Older files are deleted from the storage. The message and its alert stay until':
    'קבצים ישנים יותר נמחקים מהאחסון. ההודעה וההתראה שלה נשארות עד למגבלות שלהן תחת שמירה.',
  Discard: 'ביטול השינויים',
  'Could not test the connection.': 'לא ניתן היה לבדוק את החיבור.',
  'Database choice saved.': 'בחירת מסד הנתונים נשמרה.',
  'Could not save the database.': 'לא ניתן היה לשמור את מסד הנתונים.',
  'Iris will use SQLite again.': 'איריס תשתמש שוב ב-SQLite.',
  'Could not switch back.': 'לא ניתן היה לחזור אחורה.',
  'Could not start the copy.': 'לא ניתן היה להתחיל את ההעתקה.',
  'Where Iris keeps its data': 'איפה איריס שומרת את הנתונים שלה',
  'SQLite needs nothing to set up. Choose PostgreSQL or MySQL to keep the data on a database server.':
    'SQLite לא דורשת שום הגדרה. בחר/י PostgreSQL או MySQL כדי לשמור את הנתונים על שרת מסד נתונים.',
  Database: 'מסד נתונים',
  'Iris stores everything in one file in its data folder. Messages are searched with the':
    'איריס שומרת הכול בקובץ אחד בתיקיית הנתונים שלה. החיפוש בהודעות מתבצע באמצעות אינדקס טקסט מלא מובנה.',
  Host: 'שרת',
  Port: 'פורט',
  'Database name': 'שם מסד הנתונים',
  'Create it first and leave it empty.': 'יש ליצור אותו מראש ולהשאיר אותו ריק.',
  User: 'משתמש',
  Password: 'סיסמה',
  'Leave blank to keep the saved one. Changing the host, port or database means typing it again.':
    'יש להשאיר ריק כדי לשמור את הסיסמה השמורה. שינוי השרת, הפורט או שם מסד הנתונים דורש להקליד אותה מחדש.',
  'Saved, leave blank to keep': 'שמורה, השאר/י ריק כדי לשמור עליה',
  'Use TLS': 'שימוש ב-TLS',
  'Go back to SQLite?': 'לחזור ל-SQLite?',
  'Iris will use the SQLite file in its data folder after the next restart. Data in the other database stays where it is.':
    'איריס תשתמש בקובץ ה-SQLite שבתיקיית הנתונים שלה אחרי ההפעלה הבאה. הנתונים במסד הנתונים האחר יישארו במקומם.',
  'Use SQLite': 'שימוש ב-SQLite',
  'Move your data': 'העברת הנתונים שלך',
  'Copy phones, settings, messages and alerts into the saved database. It must be empty. Your current database is not changed.':
    'העתקת טלפונים, הגדרות, הודעות והתראות למסד הנתונים השמור. הוא חייב להיות ריק. מסד הנתונים הנוכחי שלך לא משתנה.',
  'Copy your data?': 'להעתיק את הנתונים שלך?',
  'Messages that arrive while it copies are not included. Restart Iris right after it finishes.':
    'הודעות שמגיעות בזמן ההעתקה לא ייכללו. יש להפעיל את איריס מחדש מיד לאחר שהיא מסתיימת.',
  'Copy my data': 'העתקת הנתונים שלי',
  'Too many failed attempts. Wait a few minutes, then try again.':
    'יותר מדי ניסיונות כושלים. יש להמתין כמה דקות ולנסות שוב.',
  'That username and password do not match. Check them and try again.':
    'שם המשתמש והסיסמה אינם תואמים. יש לבדוק אותם ולנסות שוב.',
  'Could not reach Iris. Check your connection and try again.':
    'לא ניתן היה להתחבר לאיריס. יש לבדוק את החיבור ולנסות שוב.',
  'Sign in · Iris': 'כניסה · איריס',
  Username: 'שם משתמש',
  'Open alerts': 'פתיחת ההתראות',
  Review: 'בדיקה',
  'Set up delivery': 'הגדרת משלוח',
  'Alert delivery is not configured, so alerts are recorded but not sent.':
    'משלוח ההתראות אינו מוגדר, כך שההתראות נרשמות אך לא נשלחות.',
  'See alerts': 'לצפייה בהתראות',
  'See why': 'לבדיקת הסיבה',
  'Check setup': 'בדיקת ההגדרה',
  'Start with the newest alert.': 'התחל/י בהתראה החדשה ביותר.',
  'Nothing urgent': 'שום דבר דחוף',
  'A few things need setting up or fixing, below.': 'יש כמה דברים שדורשים הגדרה או תיקון, למטה.',
  'All quiet': 'הכול שקט',
  Home: 'בית',
  'Could not load the dashboard. Check that Iris is running, then reload the page.':
    'לא ניתן היה לטעון את לוח הבקרה. ודא/י שאיריס פועלת ורענן/י את הדף.',
  Status: 'סטטוס',
  'Messages today': 'הודעות היום',
  'Last 7 days': '7 הימים האחרונים',
  'In the queue': 'בתור',
  Phones: 'טלפונים',
  'Media kept': 'מדיה שנשמרה',
  'Needs attention': 'דורש תשומת לב',
  'Activity, last 14 days': 'פעילות, 14 הימים האחרונים',
  'The chart appears once Iris has seen some messages.': 'התרשים יופיע ברגע שאיריס תראה הודעות.',
  'Recent alerts': 'התראות אחרונות',
  'See all': 'לצפייה בהכול',
  Chats: 'צ׳אטים',
  'Every conversation and group Iris has seen, and which phones are in them.':
    'כל שיחה וקבוצה שאיריס ראתה, ואילו טלפונים נמצאים בהן.',
  'Unnamed group': 'קבוצה ללא שם',
  'Direct chat': 'שיחה ישירה',
  'No phone linked': 'לא משויך טלפון',
  'No chats yet': 'אין עדיין צ׳אטים',
  'Chats show up here once a connected phone receives or sends a message.':
    'צ׳אטים יופיעו כאן ברגע שטלפון מחובר יקבל או ישלח הודעה.',
  'Alert dismissed.': 'ההתראה נדחתה.',
  'Marked as seen.': 'סומנה כנצפתה.',
  'Alert reopened.': 'ההתראה נפתחה מחדש.',
  'Could not update the alert. Try again.': 'לא ניתן היה לעדכן את ההתראה. נסה/י שוב.',
  'Resending the alert to your WhatsApp.': 'שולחת מחדש את ההתראה לוואטסאפ שלך.',
  'Could not resend the alert.': 'לא ניתן היה לשלוח את ההתראה מחדש.',
  Alert: 'התראה',
  'This alert no longer exists. It may have been removed by the retention window.':
    'ההתראה הזו כבר לא קיימת. ייתכן שהוסרה בשל חלון השמירה.',
  'Only the details above are kept. To see what was sent, open the chat directly in WhatsApp.':
    'רק הפרטים שלמעלה נשמרים. כדי לראות מה נשלח, יש לפתוח את הצ׳אט ישירות בוואטסאפ.',
  'The text may involve a minor, so it was not copied into the alert or sent to your':
    'לא נכלל בהתראה הזו',
  'WhatsApp. It is kept so you can read it and decide.':
    'ייתכן שהטקסט מערב קטין/ה, ולכן הוא לא הועתק להתראה או נשלח לוואטסאפ שלך. הוא נשמר כדי שתוכל/י לקרוא אותו ולהחליט.',
  'Kept media': 'מדיה שנשמרה',
  'Open on its own page': 'פתיחה בעמוד משלה',
  Delivery: 'משלוח',
  'Delivered to your WhatsApp': 'נשלחה לוואטסאפ שלך',
  'Not delivered': 'לא נשלחה',
  'Held back by the cooldown': 'נעצרה בשל תקופת הצינון',
  Sending: 'בשליחה',
  'How Iris decided': 'איך איריס החליטה',
  Alerts: 'התראות',
  'Messages Iris judged harmful, newest first.': 'הודעות שאיריס קבעה כמזיקות, החדשות ביותר קודם.',
  'Alert delivery is not set up, so alerts are saved here but not sent to your WhatsApp.':
    'משלוח ההתראות אינו מוגדר, כך שההתראות נשמרות כאן אך לא נשלחות לוואטסאפ שלך.',
  'No alerts match these filters': 'אין התראות התואמות לסינון הזה',
  'Try a different status, phone or category.': 'נסה/י סטטוס, טלפון או קטגוריה אחרים.',
  'Marked safe.': 'סומן כבטוח.',
  'Marked harmful. An alert was created.': 'סומן כמזיק. נוצרה התראה.',
  'Could not save your decision. Try again.': 'לא ניתן היה לשמור את ההחלטה שלך. נסה/י שוב.',
  'Messages Iris could not decide on, even with the chat around them. Your call.':
    'הודעות שאיריס לא הצליחה להכריע לגביהן, גם עם ההקשר שלהן. ההחלטה שלך.',
  'Nothing to review': 'אין מה לבדוק',
  'When Iris cannot tell whether a message is harmful, it waits here for you.':
    'כשאיריס לא יכולה לקבוע אם הודעה מזיקה, היא ממתינה כאן בשבילך.',
  'New webhook address created. Register it in OpenWA again.':
    'נוצרה כתובת webhook חדשה. יש לרשום אותה ב-OpenWA שוב.',
  'Could not rotate the token.': 'לא ניתן היה להחליף את האסימון.',
  'Webhook address copied.': 'כתובת ה-webhook הועתקה.',
  'Could not copy. Select the address and copy it by hand.':
    'לא ניתן היה להעתיק. יש לבחור את הכתובת ולהעתיק אותה ידנית.',
  Watching: 'במעקב',
  Paused: 'מושהה',
  'Register the webhook below, then send a test message.':
    'יש לרשום את ה-webhook למטה, ואז לשלוח הודעת בדיקה.',
  'Webhook address': 'כתובת ה-webhook',
  'Copy webhook address': 'העתקת כתובת ה-webhook',
  'Could not add the phone. Check the OpenWA address and try again.':
    'לא ניתן היה להוסיף את הטלפון. יש לבדוק את כתובת ה-OpenWA ולנסות שוב.',
  'Add a phone': 'הוספת טלפון',
  "One phone is one child's WhatsApp number, connected through an OpenWA session.":
    'טלפון אחד הוא מספר הוואטסאפ של ילד/ה אחד/ת, המחובר דרך סשן OpenWA.',
  "Child's name": 'שם הילד/ה',
  'OpenWA address': 'כתובת OpenWA',
  'OpenWA session ID': 'מזהה הסשן ב-OpenWA',
  "The full ID, not the session's name.": 'המזהה המלא, לא שם הסשן.',
  'OpenWA API key': 'מפתח API של OpenWA',
  'Phone number (optional)': 'מספר טלפון (רשות)',
  'Only shown here, to tell phones apart.': 'מוצג רק כאן, כדי להבדיל בין הטלפונים.',
  'Add phone': 'הוספת טלפון',
  "The children's numbers Iris watches. Each one connects through its own OpenWA session.":
    'מספרי הילדים שאיריס עוקבת אחריהם. כל אחד מתחבר דרך הסשן שלו ב-OpenWA.',
  'No phones yet': 'אין עדיין טלפונים',
  "Add the first child's number to start watching. You will need an OpenWA session for it.":
    'הוסיפו את המספר של הילד/ה הראשון/ה כדי להתחיל לעקוב. תצטרכו סשן OpenWA עבורו.',
  Fine: 'תקין',
  Unclear: 'כדאי לבדוק',
  Harmful: 'מזיק',
  'Iris would let this through.': 'איריס לא הייתה מסמנת את ההודעה כפוגענית.',
  'Needs a look': 'כדאי לבדוק',
  'Iris would put this in the review queue.': 'איריס הייתה שמה את זה בתור הבדיקה.',
  'Iris would alert you.': 'איריס הייתה מתריעה בפניך.',
  'Could not check the text.': 'לא ניתן היה לבדוק את הטקסט.',
  'Thresholds saved.': 'הספים נשמרו.',
  'Could not save thresholds.': 'לא ניתן היה לשמור את הספים.',
  'Try it': 'ניסיון',
  'Type a message to see how Iris would classify it, then adjust the thresholds and watch the result change.':
    'הקלד/י הודעה כדי לראות איך איריס הייתה מסווגת אותה, ואז כוונ/י את הסף וצפ/י בתוצאה משתנה.',
  'Use at most 20 earlier messages of up to 1,000 characters each.':
    'יש להשתמש בעד 20 הודעות קודמות של עד 1,000 תווים כל אחת.',
  'Message to check': 'הודעה לבדיקה',
  'Earlier messages in the chat (optional)': 'הודעות קודמות בצ׳אט (רשות)',
  'One per line, oldest first (up to 20). Iris uses them for the second look when the first check is unclear.':
    'אחת בכל שורה, הישנה ביותר קודם (עד 20). איריס משתמשת בהן למבט השני כשהבדיקה הראשונה אינה ברורה.',
  'Checking…': 'בודקת…',
  Check: 'בדיקה',
  'The text is sent to OpenAI for moderation and is not stored by Iris.':
    'הטקסט נשלח ל-OpenAI לבדיקת תוכן ואינו נשמר על ידי איריס.',
  'First check': 'בדיקה ראשונה',
  'Second look': 'מבט שני',
  'Each row shows the first check on top and the second look below it. Orange marks':
    'כל שורה מציגה את הבדיקה הראשונה למעלה ואת המבט השני מתחתיה. כתום מסמן "כדאי לבדוק", אדום מסמן "מזיק".',
  'Checking this message again.': 'בודקת את ההודעה הזו שוב.',
  'Could not re-check the message.': 'לא ניתן היה לבדוק את ההודעה מחדש.',
  'Group conversation': 'שיחה קבוצתית',
  Conversation: 'שיחה',
  'Messages in this conversation': 'הודעות בשיחה הזו',
  Unknown: 'לא ידוע/ה',
  'Trying again.': 'מנסה שוב.',
  'Could not retry the job.': 'לא ניתן היה לנסות את המשימה שוב.',
  Jobs: 'משימות',
  'Work that failed or ran out of attempts. Fix the cause shown, then try again.':
    'עבודה שנכשלה או שאזלו לה הניסיונות. תקנ/י את הסיבה שמוצגת, ואז נסה/י שוב.',
  'See the message': 'צפייה בהודעה',
  'No failed jobs': 'אין משימות שנכשלו',
  'If a message cannot be checked or an alert cannot be sent, it appears here with the':
    'אם לא ניתן לבדוק הודעה או לשלוח התראה, זה יופיע כאן עם הסיבה.',
  Messages: 'הודעות',
  'Everything Iris has seen. Search covers messages and voice-note transcripts, in Hebrew and English.':
    'כל מה שאיריס ראתה. החיפוש כולל הודעות ותמלולי הודעות קוליות, בעברית ובאנגלית.',
  'Search messages': 'חיפוש הודעות',
  'Search words, names or transcripts': 'חיפוש מילים, שמות או תמלולים',
  When: 'מתי',
  'No messages match': 'אין הודעות תואמות',
  'No messages yet': 'אין עדיין הודעות',
  'Clear search and filters': 'ניקוי חיפוש וסינונים',
  'Try fewer words or remove a filter.': 'נסה/י פחות מילים או הסר/י סינון.',
  'Messages appear here a few seconds after a phone receives or sends them.':
    'הודעות מופיעות כאן כמה שניות אחרי שטלפון מקבל או שולח אותן.',
  'This file is no longer kept': 'הקובץ הזה כבר לא נשמר',
  'It was deleted when its keep time ended, or it was withheld. The message itself may still':
    'הוא נמחק כשזמן השמירה שלו הסתיים, או נחסם. ייתכן שההודעה עצמה עדיין קיימת באיריס.',
  'Some parents notified': 'חלק מההורים קיבלו התראה',
  'Held back': 'השליחה הושהתה',
  'Content withheld. Review the chat directly.': 'התוכן הוסתר. יש לבדוק את השיחה ישירות.',
  'Kept out of the alert. Open it to read.': 'לא נכלל בהתראה. יש לפתוח כדי לקרוא.',
  'Edit phone': 'עריכת טלפון',
  'Update this Iris connection. OpenWA credentials are checked when changed.':
    'עדכון חיבור הטלפון באיריס. פרטי OpenWA נבדקים כשמשנים אותם.',
  'Display name': 'שם לתצוגה',
  'Session name in Iris': 'שם החיבור באיריס',
  'An Iris label only. This OpenWA version does not support renaming its session through the API.':
    'זהו שם לתצוגה באיריס בלבד. גרסת OpenWA הזו אינה מאפשרת שינוי שם החיבור דרך ה־API.',
  'Phone role': 'תפקיד הטלפון',
  'Parent alert sender': 'טלפון לשליחת התראות להורים',
  'Monitor this child': 'ניטור הילד או הילדה',
  'OpenWA-generated ID. Changing it selects a different existing session.':
    'מזהה שנוצר ב־OpenWA. שינויו בוחר חיבור קיים אחר.',
  'Leave blank to keep the stored key. A new address requires a new key.':
    'השאירו ריק כדי לשמור על המפתח הקיים. כתובת חדשה מחייבת מפתח חדש.',
  'Phone number': 'מספר טלפון',
  'Changes could not be saved.': 'לא ניתן לשמור את השינויים.',
  'After changing a child’s OpenWA session, register its webhook again.':
    'לאחר שינוי חיבור הילד ב־OpenWA יש לרשום מחדש את כתובת קבלת ההודעות.',
  'Saving…': 'שומר…',
  'Save changes': 'שמירת השינויים',
  'App installed': 'האפליקציה מותקנת',
  'Install app': 'התקנת האפליקציה',
  'Install Iris': 'התקנת איריס',
  'Use Iris as a desktop or Android app.': 'אפשר להשתמש באיריס כאפליקציה במחשב או ב־Android.',
  'Iris is already running as an installed app.': 'איריס כבר פועלת כאפליקציה מותקנת.',
  'In Chrome on Android, open the browser menu and choose Add to home screen, then Install. On desktop Chrome, choose Install Iris from the address bar or browser menu.':
    'ב־Chrome ב־Android פתחו את תפריט הדפדפן, בחרו הוספה למסך הבית ואז התקנה. במחשב בחרו התקנת איריס בשורת הכתובת או בתפריט הדפדפן.',
  'Open Iris through an HTTPS address to enable app installation. This HTTP address may only support a browser shortcut.':
    'כדי להתקין את האפליקציה יש לפתוח את איריס בכתובת HTTPS. כתובת HTTP עשויה לאפשר רק קיצור דרך לדפדפן.',
  'The app needs access to your Iris server. It does not provide background notifications or offline monitoring status.':
    'האפליקציה זקוקה לחיבור לשרת איריס. היא אינה מספקת התראות ברקע או מצב ניטור ללא חיבור.',
  'Could not check this session.': 'לא ניתן לבדוק את החיבור הזה.',
  'Could not register the webhook.': 'לא ניתן לרשום את כתובת קבלת ההודעות.',
  'Could not change this phone.': 'לא ניתן לעדכן את הטלפון הזה.',
  'Could not change the phone role.': 'לא ניתן לשנות את תפקיד הטלפון.',
  'Could not remove this phone.': 'לא ניתן להסיר את הטלפון הזה.',
  'Monitoring enabled': 'הניטור פעיל',
  'Parent connection': 'חיבור הורה',
  'WhatsApp connected': 'WhatsApp מחובר',
  'WhatsApp needs re-pairing': 'נדרש קישור מחדש ל־WhatsApp',
  'WhatsApp disconnected': 'WhatsApp מנותק',
  'WhatsApp connecting': 'מתחבר ל־WhatsApp',
  'OpenWA unreachable': 'לא ניתן להתחבר ל־OpenWA',
  'OpenWA session missing': 'חיבור OpenWA לא נמצא',
  'WhatsApp connection failed': 'החיבור ל־WhatsApp נכשל',
  'Connection not checked': 'החיבור טרם נבדק',
  'Check connection': 'בדיקת החיבור',
  'Monitoring is enabled, but this phone is not connected. New messages cannot be checked until WhatsApp reconnects.':
    'הניטור מופעל, אך הטלפון אינו מחובר. לא ניתן לבדוק הודעות חדשות עד ש־WhatsApp יתחבר מחדש.',
  'Child — monitored when watching is enabled': 'ילד או ילדה — מנוטר כשהמעקב מופעל',
  'Parent — alert delivery only': 'הורה — שליחת התראות בלבד',
  'Last message received': 'ההודעה האחרונה התקבלה',
  'Nothing received yet': 'עדיין לא התקבלו הודעות',
  'Register in OpenWA': 'רישום ב־OpenWA',
  'New webhook address': 'כתובת קבלת הודעות חדשה',
  'Create a new webhook address?': 'ליצור כתובת חדשה לקבלת הודעות?',
  'Create new address': 'יצירת כתובת חדשה',
  "Used for alert delivery. This phone's messages are not monitored. Choose the alert sender in":
    'משמש לשליחת התראות. הודעות הטלפון הזה אינן מנוטרות. את שולח ההתראות בוחרים ב',
  'This parent connection is removed. Select another sender in Settings if it is used for alert delivery.':
    'חיבור ההורה יוסר. אם הוא משמש לשליחת התראות, יש לבחור שולח אחר בהגדרות.',
  'Iris stops watching this phone. Messages already saved stay until the retention window removes them.':
    'איריס תפסיק לנטר את הטלפון. הודעות שכבר נשמרו יישארו עד תום תקופת השמירה.',
  'Remove phone': 'הסרת הטלפון',
  'Also delete the OpenWA session': 'מחיקת החיבור גם ב־OpenWA',
  'Unlinks WhatsApp and deletes its saved session. Leave unchecked to remove only from Iris.':
    'מנתק את WhatsApp ומוחק את החיבור השמור. להסרה מאיריס בלבד, אין לסמן אפשרות זו.',
  'Phone removal progress': 'התקדמות הסרת הטלפון',
  'Phone removed.': 'הטלפון הוסר.',
  'Deactivating WhatsApp…': 'מנתק את WhatsApp…',
  'Deleting the OpenWA session…': 'מוחק את חיבור OpenWA…',
  'Removing the Iris entry…': 'מסיר את הטלפון מאיריס…',
  'Deactivate WhatsApp': 'ניתוק WhatsApp',
  'Delete OpenWA session': 'מחיקת חיבור OpenWA',
  'Remove Iris entry': 'הסרה מאיריס',
  'You can retry removal.': 'אפשר לנסות להסיר שוב.',
  'Could not save the name. The phone is already connected.':
    'לא ניתן לשמור את השם. הטלפון כבר מחובר.',
  'Add a child phone to monitor its messages.':
    'הוסיפו טלפון של ילד או ילדה כדי לנטר את ההודעות שלו.',
  'Add a WhatsApp sender connection for parent alerts. Sender messages are not monitored.':
    'הוסיפו חיבור WhatsApp שישלח התראות להורים. הודעות השולח אינן מנוטרות.',
  "Parent's name": 'שם ההורה',
  'Connected phone: +': 'הטלפון המחובר: +',
  'Saving the paired phone in Iris…': 'שומר את הטלפון המקושר באיריס…',
  'The phone could not be saved.': 'לא ניתן לשמור את הטלפון.',
  'Retry saving phone': 'ניסיון נוסף לשמירת הטלפון',
  'Phone connected': 'הטלפון מחובר',
  'Already saved in Iris. You can optionally give it a friendly name.':
    'הטלפון כבר נשמר באיריס. אפשר לתת לו שם נוח לתצוגה.',
  "Parent's name (optional)": 'שם ההורה (רשות)',
  "Child's name (optional)": 'שם הילד או הילדה (רשות)',
  'Save name': 'שמירת השם',
  'Parent recipients saved.': 'הנמענים נשמרו.',
  'Could not save parent recipients.': 'לא ניתן לשמור את נמעני ההתראות.',
  'Parent alert recipients': 'הורים שמקבלים התראות',
  'These numbers receive alerts. They do not need their own OpenWA session. Up to ten recipients.':
    'המספרים האלה יקבלו התראות. אין צורך בחיבור OpenWA נפרד עבורם. אפשר להוסיף עד עשרה נמענים.',
  'No parent recipients yet.': 'עדיין אין נמענים להתראות.',
  'Parent phone number': 'מספר הטלפון של ההורה',
  'Include the country code and omit the local leading zero. The + prefix is optional.':
    'יש לכלול את קידומת המדינה ולהשמיט את האפס הראשון במספר המקומי. הסימן + אינו חובה.',
  'Enter an international phone number with its country code, for example +15550100101.':
    'יש להזין מספר בינלאומי עם קידומת מדינה, למשל ‎+15550100101.',
  'Add parent': 'הוספת הורה',
  'Number format is checked when saved. Ownership and WhatsApp registration are not verified.':
    'מבנה המספר נבדק בשמירה. הבעלות על המספר וההרשמה ל־WhatsApp אינן נבדקות.',
  'Alert sender connections': 'חיבורים לשליחת התראות',
  'One connected WhatsApp number sends alerts to all parent recipients. Sender connections are not monitored.':
    'מספר WhatsApp מחובר אחד שולח התראות לכל ההורים ברשימה. חיבורי השולחים אינם מנוטרים.',
  'Two or more sender connections are optional. You can keep a primary, secondary and additional backup sender in case a number is blocked or disconnected. If the active sender becomes unavailable, manually select another connected sender below. Iris does not switch senders automatically.':
    'אפשר להגדיר כמה שולחים לגיבוי למקרה שהמספר נחסם או מתנתק. אם השולח הפעיל אינו זמין, יש לבחור ידנית שולח מחובר אחר למטה. איריס אינה מחליפה שולחים אוטומטית.',
  'Loading sender connections…': 'טוען את חיבורי השולחים…',
  'Retry loading sender connections': 'ניסיון נוסף לטעינת חיבורי השולחים',
  'No alert sender connected yet.': 'עדיין אין שולח התראות מחובר.',
  'OpenWA connection failed. No QR is available.': 'החיבור ל־OpenWA נכשל. אין קוד QR זמין.',
  'Cleanup is waiting for OpenWA. It will retry automatically; you can retry here too.':
    'הניקוי ממתין ל־OpenWA וינסה שוב אוטומטית. אפשר לנסות שוב גם כאן.',
  'Cleanup failed.': 'הניקוי נכשל.',
  'Pair a new phone with QR': 'קישור טלפון חדש באמצעות QR',
  'Get the QR code and link WhatsApp first. You can add an optional name after pairing. Iris uses the server’s configured OpenWA connection.':
    'קבלו קוד QR וקשרו תחילה את WhatsApp. אפשר להוסיף שם לאחר הקישור. איריס משתמשת בחיבור OpenWA שהוגדר בשרת.',
  'Connecting to OpenWA…': 'מתחבר ל־OpenWA…',
  'Get pairing QR': 'קבלת קוד QR לקישור',
  'Pairing started. Creating and starting your OpenWA session…':
    'הקישור התחיל. יוצר ומפעיל חיבור OpenWA…',
  'Scan received. Waiting for WhatsApp to confirm the connection…':
    'הסריקה התקבלה. ממתין לאישור החיבור מ־WhatsApp…',
  'OpenWA is starting WhatsApp. Waiting for the QR code…':
    'OpenWA מפעיל את WhatsApp. ממתין לקוד QR…',
  'Session started. Waiting for OpenWA to generate a QR code…':
    'החיבור הופעל. ממתין ליצירת קוד QR ב־OpenWA…',
  'Waiting for WhatsApp pairing': 'ממתין לקישור WhatsApp',
  'Elapsed:': 'זמן שחלף:',
  's. Iris checks for updates every 2 seconds.': 'שניות. איריס בודקת עדכונים כל שתי שניות.',
  'OpenWA is taking longer to respond. Keep this window open; the QR will appear automatically when available.':
    'OpenWA מתעכב בתגובה. השאירו את החלון פתוח; קוד QR יופיע אוטומטית כשיהיה זמין.',
  'WhatsApp pairing QR code': 'קוד QR לקישור WhatsApp',
  'QR image could not be displayed. Requesting a fresh code…':
    'לא ניתן להציג את קוד QR. מבקש קוד חדש…',
  'WhatsApp connected. Iris is saving this phone automatically.':
    'WhatsApp מחובר. איריס שומרת את הטלפון אוטומטית.',
  'WhatsApp → Linked devices → Link a device. QR refreshes automatically.':
    'ב־WhatsApp: מכשירים מקושרים ← קישור מכשיר. קוד QR מתרענן אוטומטית.',
  'OpenWA unavailable. The QR has been removed.': 'OpenWA אינו זמין. קוד QR הוסר.',
  'Waiting for OpenWA to provide a fresh QR or confirm the connection…':
    'ממתין לקוד QR חדש או לאישור החיבור מ־OpenWA…',
  'Refresh QR': 'רענון QR',
  'Cancel pairing': 'ביטול הקישור',
  'Closing before pairing is saved removes the temporary OpenWA session. After Iris saves the paired phone, closing the optional name step keeps the connection. If a connection is lost, server cleanup retries after the pairing lease expires. Existing sessions are never removed.':
    'סגירה לפני שמירת הקישור מסירה את חיבור OpenWA הזמני. לאחר השמירה אפשר לסגור את שלב השם בלי לנתק. אם החיבור אבד, השרת ינסה לנקות את החיבור הזמני בהמשך. חיבורים קיימים אינם מוסרים.',
  'Webhook registration failed. Retry below.':
    'רישום כתובת קבלת ההודעות נכשל. אפשר לנסות שוב למטה.',
  'Re-pair WhatsApp': 'קישור WhatsApp מחדש',
  'Reconnect the existing WhatsApp session. Closing this window never deletes your phone or session.':
    'קישור מחדש של חיבור WhatsApp הקיים. סגירת החלון אינה מוחקת את הטלפון או את החיבור.',
  'WhatsApp re-pairing QR code': 'קוד QR לקישור מחדש של WhatsApp',
  'Connected. Restoring monitoring…': 'מחובר. מחזיר את הניטור לפעולה…',
  'Scan received. Confirming WhatsApp connection…': 'הסריקה התקבלה. מאמת את חיבור WhatsApp…',
  'WhatsApp → Linked devices → Link a device. QR changes update automatically.':
    'ב־WhatsApp: מכשירים מקושרים ← קישור מכשיר. שינויי קוד QR מתעדכנים אוטומטית.',
  'Connection check failed.': 'בדיקת החיבור נכשלה.',
  'Checking the existing session and waiting for OpenWA to provide a QR…':
    'בודק את החיבור הקיים וממתין לקוד QR מ־OpenWA…',
  'OpenWA unavailable': 'OpenWA אינו זמין',
  'Retry restoring monitoring': 'ניסיון נוסף להפעלת הניטור',
  'Refresh QR / check connection': 'רענון QR / בדיקת החיבור',
  'Add a child': 'הוספת ילד או ילדה',
  'No child phone is configured. Iris cannot monitor children yet.':
    'לא הוגדר טלפון של ילד או ילדה. איריס עדיין אינה יכולה לנטר ילדים.',
  'Add parents': 'הוספת הורים',
  'No parent recipients are configured. Add a parent phone number to receive alerts.':
    'לא הוגדרו נמענים להתראות. הוסיפו מספר טלפון של הורה לקבלת ההתראות.',
  'Set alert phone': 'הגדרת טלפון להתראות',
  'No alert phone is set. Connect a sender phone and select it to send alerts to parents.':
    'לא הוגדר טלפון לשליחת התראות. חברו טלפון ובחרו בו כשולח.',
  'Check sessions': 'בדיקת החיבורים',
  'A monitored phone or the alert sender is disconnected or unreachable. Monitoring or delivery may have stopped.':
    'טלפון מנוטר או שולח ההתראות מנותק או אינו זמין. ייתכן שהניטור או השליחה נעצרו.',
  'Check recipients': 'בדיקת הנמענים',
  'The sender is also a parent recipient. Messages to yourself may not notify you; use a separate sender phone for reliable parent notifications.':
    'השולח מופיע גם כנמען. הודעות לעצמך עשויות לא להתריע; לשליחה אמינה להורים מומלץ טלפון שולח נפרד.',
  'Check delivery': 'בדיקת השליחה',
  'Some alerts reached only part of the parent recipient list.':
    'חלק מההתראות הגיעו רק לחלק מההורים ברשימה.',
  'Monitoring or alert delivery needs setting up or fixing, below.':
    'יש להגדיר או לתקן את הניטור או את שליחת ההתראות למטה.',
  'Iris is watching. Nothing has come in today yet.': 'איריס מנטרת. עדיין לא התקבלו הודעות היום.',
  'Loading the dashboard': 'טוען את לוח הבקרה',
  'Alert recipients': 'נמעני ההתראות',
  'Alert phones': 'טלפונים להתראות',
  'Sender connections': 'חיבורי שולחים',
  'No alerts yet': 'אין עדיין התראות',
  'When a message needs your attention, Iris lists it here and sends it to your WhatsApp.':
    'כשנדרשת תשומת לב להודעה, איריס מציגה אותה כאן ושולחת התראה ל־WhatsApp שלך.',
  'Manage monitored children. Parent recipients and sender connections are in Settings → Alerts.':
    'ניהול הילדים המנוטרים. נמענים וחיבורים לשליחת התראות נמצאים בהגדרות ← התראות.',
  'Not set': 'לא מוגדר',
  'Remove the saved key?': 'להסיר את המפתח השמור?',
  'Iris stops using it until you enter a new one. Checks that need it will fail in the meantime.':
    'איריס תפסיק להשתמש במפתח עד להזנת מפתח חדש. בדיקות שדורשות אותו ייכשלו בינתיים.',
  'Remove key': 'הסרת המפתח',
  'Delete all kept media': 'מחיקת כל המדיה השמורה',
  'Needs a look from': 'דורש בדיקה מציון',
  'Harmful from': 'פוגעני מציון',
  'Reset all to defaults': 'איפוס הכול לברירת המחדל',
  'A score at or above the harmful level is flagged. Between the two levels Iris is unsure: it looks again with the chat around the message, then asks you to review it if still unclear.':
    'ציון בסף הפוגעני או מעליו מסומן. בין הספים איריס בודקת שוב עם ההקשר בשיחה, ואם עדיין לא ברור מבקשת בדיקה ידנית.',
  'Not saved. Check your connection and try again.': 'לא נשמר. יש לבדוק את החיבור ולנסות שוב.',
  'Classification provider': 'ספק לסיווג תוכן',
  'Choose how Iris classifies messages. Saved choices override server environment defaults.':
    'בחירת הדרך לסיווג הודעות. הגדרות שמורות גוברות על ברירות המחדל של השרת.',
  'Ollama (local)': 'Ollama (מקומי)',
  'Local text classifier. Test the entered endpoint and model, then save to use them for new jobs.':
    'סיווג טקסט מקומי. בדקו את כתובת השירות והמודל ואז שמרו לשימוש במשימות חדשות.',
  'Ollama endpoint': 'כתובת Ollama',
  'Ollama model': 'מודל Ollama',
  'Local scores require calibration. Images and stickers require manual review in local safety mode.':
    'ציוני הסיווג המקומי דורשים כיול. תמונות ומדבקות דורשות בדיקה ידנית במצב בטיחות מקומי.',
  'Test Ollama': 'בדיקת Ollama',
  'Transcription provider': 'ספק לתמלול',
  'Choose local transcription, OpenAI, or Cloudflare. No automatic cloud fallback is used.':
    'בחירת תמלול מקומי, OpenAI או Cloudflare. אין מעבר אוטומטי לספק ענן.',
  'Cloudflare Workers AI': 'Cloudflare Workers AI',
  'Mila companion / local Whisper': 'שרת Mila / Whisper מקומי',
  'Active local transcription API. The Mila desktop app itself does not provide this API.':
    'שירות API פעיל לתמלול מקומי. אפליקציית Mila במחשב אינה מספקת את ה־API הזה.',
  'Transcription endpoint': 'כתובת שירות התמלול',
  'Local transcription model': 'מודל תמלול מקומי',
  'Local transcription API key': 'מפתח API לתמלול מקומי',
  'Use environment API key when no saved key exists': 'שימוש במפתח מהגדרות השרת כשאין מפתח שמור',
  'Fallback model (optional)': 'מודל חלופי (רשות)',
  'Audio and video audio tracks are transcribed. Test the endpoint, model and key before saving. Changing the host requires re-entering the API key.':
    'שמע ופסי הקול של סרטונים מתומללים. בדקו את השירות, המודל והמפתח לפני השמירה. שינוי השרת מחייב הזנה מחדש של המפתח.',
  'Test transcription connection': 'בדיקת חיבור התמלול',
  'Processing mode': 'מצב עיבוד',
  'Safety mode keeps unexamined media for review. Worker changes apply to new jobs; in-flight jobs finish.':
    'מצב בטיחות משאיר מדיה שלא נבדקה לבדיקה ידנית. שינוי מספר תהליכי העיבוד חל על משימות חדשות; משימות שכבר התחילו מסתיימות כרגיל.',
  'Local safety mode': 'מצב בטיחות מקומי',
  'Require signed webhooks': 'דרישה לחתימה על הודעות נכנסות',
  'Classification workers (0 pauses processing)': 'תהליכי סיווג (0 משהה את העיבוד)',
  'Dedicated alert workers': 'תהליכי שליחת התראות',
  'Job heartbeat seconds (0 disables)': 'מרווח בדיקת פעילות המשימות בשניות (0 מכבה)',
  'Monitoring silence minutes (0 disables)': 'התראה על היעדר הודעות בדקות (0 מכבה)',
  'OpenAI moderation model': 'מודל סיווג התוכן של OpenAI',
  'Iris sends each alert to every listed parent from one linked WhatsApp phone. Up to 10 recipients.':
    'איריס שולחת כל התראה לכל ההורים ברשימה מטלפון WhatsApp מקושר אחד. אפשר להגדיר עד עשרה נמענים.',
  'What to keep': 'מה לשמור',
  'Content Iris withholds (anything sexual involving minors, or sexual images) is never kept, whatever you choose. Videos are not kept at all, because Iris checks what a video says, not what it shows.':
    'תוכן שהוסתר לאחר הסיווג אינו נשמר כמדיה, בכל מדיניות שמירה. סרטונים אינם נשמרים, משום שאיריס בודקת את פס הקול ולא את התמונה.',
  'Where to keep it': 'איפה לשמור',
  'This server&apos;s disk': 'הדיסק של השרת הזה',
  'S3-compatible storage': 'אחסון תואם S3',
  'Files go to the': 'הקבצים נשמרים ב',
  'folder inside Iris&apos;s data folder, next to the database. In Docker that is the data volume.':
    'בתוך תיקיית הנתונים של איריס, ליד מסד הנתונים. ב־Docker זהו נפח הנתונים.',
  'Works with Cloudflare R2, AWS S3, SeaweedFS, MinIO and other S3-compatible services. Create the bucket first.':
    'תומך ב־Cloudflare R2, AWS S3, SeaweedFS, MinIO ושירותים תואמי S3 נוספים. יש ליצור קודם את מכל האחסון.',
  'Older files are deleted from the storage. The message and its alert stay until their own limits under Retention.':
    'קבצים ישנים נמחקים מהאחסון. ההודעה וההתראה נשארות עד תום תקופות השמירה שלהן.',
  'You have unsaved changes.': 'יש שינויים שלא נשמרו.',
  Child: 'ילד או ילדה',
  Parent: 'הורה',
  Checked: 'נבדק',
  Remove: 'הסרה',
  Manual: 'ידני',
  Automatic: 'אוטומטי',
  Done: 'בוצע',
  Close: 'סגירה',
  Cancel: 'ביטול',
  Children: 'ילדים',
  Parents: 'הורים',
  Providers: 'ספקים',
  Classification: 'סיווג',
  Scope: 'היקף הניטור',
  Retention: 'שמירה',
  Media: 'מדיה',
  Account: 'חשבון',
  Clear: 'ניקוי',
  Test: 'בדיקה',
  Testing: 'בודק',
  Category: 'קטגוריה',
  Storage: 'אחסון',
  Save: 'שמירה',
  'Edit {name}': 'עריכת {name}',
  'Webhook registered in OpenWA for {name}.': 'כתובת קבלת ההודעות נרשמה ב־OpenWA עבור {name}.',
  'Watching {name} again.': 'הניטור של {name} הופעל מחדש.',
  'Paused watching {name}.': 'הניטור של {name} הושהה.',
  '{name} removed.': '{name} הוסר.',
  'Watch {name}': 'ניטור {name}',
  'Role for {name}': 'תפקיד הטלפון של {name}',
  "The current address stops working immediately. You must register the new one in OpenWA before {name}'s messages are checked again.":
    'הכתובת הנוכחית מפסיקה לפעול מיד. יש לרשום כתובת חדשה ב־OpenWA לפני שהודעות {name} ייבדקו שוב.',
  'Remove {name}?': 'להסיר את {name}?',
  '{name} added. Register the webhook to start watching.':
    '{name} נוסף. יש לרשום את כתובת קבלת ההודעות כדי להתחיל בניטור.',
  'Current name: {name}': 'השם הנוכחי: {name}',
  'Remove parent {name}': 'הסרת ההורה {name}',
  'Re-pair {name}': 'קישור מחדש של {name}',
  'Enter a number for "{name}".': 'יש להזין מספר עבור "{name}".',
}

export function he(value: string, variables: Record<string, string | number> = {}): string {
  return (language === 'he' ? (text[value] ?? value) : value).replace(
    /\{(\w+)\}/g,
    (match, key: string) => String(variables[key] ?? match),
  )
}
