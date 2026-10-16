import { language } from './language'

/** Translate server validation text for display while keeping API payloads unchanged. */
const messages: Record<string, string> = {
  'Alert delivery is not configured': 'שליחת ההתראות עדיין לא הוגדרה',
  'Alert not found': 'ההתראה לא נמצאה',
  'Already queued or running': 'המשימה כבר ממתינה בתור או מתבצעת',
  'Cloudflare account ID is 32 hex characters':
    'מזהה חשבון Cloudflare צריך להכיל 32 תווים הקסדצימליים',
  'Delivery already in progress': 'השליחה כבר מתבצעת',
  'Instance not found': 'חיבור הטלפון לא נמצא',
  'Invalid credentials': 'פרטי ההתחברות אינם נכונים',
  'Message is not awaiting review': 'ההודעה אינה ממתינה לבדיקה',
  'Message not found': 'ההודעה לא נמצאה',
  'Not authenticated': 'יש להתחבר מחדש',
  'Only failed or dead jobs can be retried': 'אפשר לנסות מחדש רק משימות שנכשלו או הופסקו',
  'OpenWA API key is not set': 'מפתח ה־API של OpenWA עדיין לא הוגדר',
  'OpenWA base URL address is not allowed': 'כתובת OpenWA אינה מותרת',
  'OpenWA base URL must be http(s) with a host':
    'כתובת OpenWA צריכה להתחיל ב־http:// או ב־https:// ולכלול שם שרת',
  'Password must be at least 8 characters': 'הסיסמה צריכה להכיל לפחות 8 תווים',
  'Re-enter the API key when changing the base URL':
    'בשינוי כתובת השרת יש להזין מחדש את מפתח ה־API',
  'Redacted messages cannot be reprocessed': 'אי אפשר לבדוק מחדש הודעות שתוכנן הוסתר',
  'That address is not allowed.': 'הכתובת אינה מותרת',
  'The endpoint must be just a host (and optional port and path).':
    'כתובת השירות צריכה לכלול שרת בלבד, ובמידת הצורך פורט ונתיב',
  'The endpoint must start with http:// or https:// and name a host.':
    'כתובת השירות צריכה להתחיל ב־http:// או ב־https:// ולכלול שם שרת',
  "The endpoint's port is not valid.": 'הפורט בכתובת השירות אינו תקין',
  'Too many failed attempts': 'נכשלו יותר מדי ניסיונות. יש להמתין כמה דקות ולנסות שוב',
  'bad signature': 'חתימת הבקשה אינה תקינה',
  'could not store message': 'לא ניתן לשמור את ההודעה',
  'database unreachable': 'לא ניתן להתחבר למסד הנתונים',
  'enter a host name or IP address': 'יש להזין שם שרת או כתובת IP',
  'enter the database name': 'יש להזין את שם מסד הנתונים',
  'enter the database user': 'יש להזין את שם המשתמש במסד הנתונים',
  'model looks like @cf/<vendor>/<name>': 'שם המודל צריך להיות בפורמט @cf/<vendor>/<name>',
  'must be a non-empty string': 'יש להזין טקסט שאינו ריק',
  'must be an integer': 'יש להזין מספר שלם',
  'must be an object of {category: {low, high}}': 'יש להזין סף נמוך וגבוה לכל קטגוריה',
  'must be true or false': 'יש לבחור כן או לא',
  'no stage applied to this message': 'לא נמצא תוכן מתאים לבדיקה בהודעה',
  'signature required': 'נדרשת חתימה לבקשה',
  'text must not be blank': 'יש להזין טקסט לבדיקה',
  'the port must be between 1 and 65535': 'הפורט צריך להיות בין 1 ל־65535',
  'unknown database type': 'סוג מסד הנתונים אינו מוכר',
  'unknown timezone (use an IANA name like Asia/Jerusalem)':
    'אזור הזמן אינו מוכר. יש להשתמש בשם כגון Asia/Jerusalem',
  'use 3-63 lowercase letters, digits, dots or hyphens':
    'יש להשתמש ב־3 עד 63 אותיות אנגליות קטנות, ספרות, נקודות או מקפים',
  'use letters, digits, dots, hyphens and slashes':
    'יש להשתמש באותיות, ספרות, נקודות, מקפים ולוכסנים',
  'workers not running': 'תהליכי עיבוד ההודעות אינם פועלים',
  'Field required': 'שדה חובה',
  'Connected.': 'החיבור הצליח.',
  'Connected. It already holds Iris data, so your data cannot be copied into it.':
    'החיבור הצליח. מסד הנתונים כבר מכיל נתוני איריס, ולכן אי אפשר להעתיק אליו נתונים.',
  'The user name or password was refused.': 'שם המשתמש או הסיסמה נדחו.',
  'Could not reach the server.': 'לא ניתן להתחבר לשרת.',
  'The new database already contains data.': 'מסד הנתונים החדש כבר מכיל נתונים.',
  'No OpenAI API key set': 'מפתח OpenAI עדיין לא הוגדר',
  'OpenAI Moderation answered': 'החיבור לסיווג התוכן של OpenAI הצליח',
  'Cloudflare account ID and API token are required': 'נדרשים מזהה חשבון ומפתח API של Cloudflare',
  'Cloudflare Workers AI transcribed the test clip': 'Cloudflare Workers AI תמלל את קטע הבדיקה',
  'Storage works: a test file was written, read and deleted.':
    'האחסון עובד: קובץ בדיקה נכתב, נקרא ונמחק.',
  'Too many tests. Wait a few minutes and try again.':
    'בוצעו יותר מדי בדיקות. יש להמתין כמה דקות ולנסות שוב.',
  'Choose an alert sender instance that has an OpenWA API key':
    'יש לבחור חיבור לשליחת התראות עם מפתח OpenWA',
  'Enter the alert recipient (phone number or chat ID)':
    'יש להזין מספר טלפון או מזהה שיחה לקבלת ההתראות',
  'Test alert sent': 'התראת הבדיקה נשלחה',
}
function fallback(status: number): string {
  if (language === 'en') {
    if (status === 401) return 'Sign in again or check your credentials'
    if (status === 403) return 'You do not have permission to do this'
    if (status === 404) return 'The requested item was not found'
    if (status === 400 || status === 422)
      return 'Some details are invalid. Check the fields and try again'
    if (status === 429) return 'Too many requests. Wait and try again'
    return `Request failed (code ${status}). Try again`
  }
  if (status === 401) return 'יש להתחבר מחדש או לבדוק את פרטי ההתחברות'
  if (status === 403) return 'אין הרשאה לבצע את הפעולה'
  if (status === 404) return 'הפריט המבוקש לא נמצא'
  if (status === 422 || status === 400)
    return 'חלק מהפרטים אינם תקינים. יש לבדוק את השדות ולנסות שוב'
  if (status === 429) return 'נשלחו יותר מדי בקשות. יש להמתין ולנסות שוב'
  return `הפעולה נכשלה (קוד ${status}). יש לנסות שוב`
}
export function apiErrorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') {
    if (messages[detail]) return language === 'he' ? messages[detail] : detail
    if (language === 'he' && /[\u0590-\u05ff]/.test(detail)) return detail
    const range = detail.match(/^must be an integer between (\d+) and (\d+)$/)
    if (range)
      return language === 'he'
        ? `יש להזין מספר שלם בין ${range[1]} ל־${range[2]}`
        : `Enter an integer between ${range[1]} and ${range[2]}`
    if (detail.startsWith('database.json cannot be read'))
      return language === 'he'
        ? 'לא ניתן לקרוא את הגדרות מסד הנתונים. יש לבדוק את מפתח ההצפנה וההגדרות.'
        : 'Cannot read database settings. Check the encryption key and configuration.'
    const charset = detail.match(/^The database uses ([\w-]+)\./)
    if (charset)
      return language === 'he'
        ? `מסד הנתונים משתמש בערכת התווים ${charset[1]}. מומלץ utf8mb4 לשמירת עברית ואמוג׳י`
        : `The database uses ${charset[1]}. Use utf8mb4 for Unicode and emoji.`
    if (status === 200) return language === 'he' ? 'הבדיקה הצליחה' : 'The check succeeded'
    return fallback(status)
  }
  if (Array.isArray(detail)) {
    return (
      detail
        .map((e: unknown) => {
          if (!e || typeof e !== 'object') return fallback(status)
          return apiErrorMessage((e as { msg?: unknown }).msg, status)
        })
        .join(' · ') || fallback(status)
    )
  }
  if (detail && typeof detail === 'object') {
    return (
      Object.entries(detail)
        .map(([field, error]) => `${field}: ${apiErrorMessage(error, status)}`)
        .join(' · ') || fallback(status)
    )
  }
  return fallback(status)
}
