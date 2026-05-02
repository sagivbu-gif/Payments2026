import streamlit as st
import pandas as pd
import gspread
import google.generativeai as genai
import json
from google.oauth2.service_account import Credentials

# --- הגדרות תצורה ומשתנים גלובליים ---
st.set_page_config(page_title="ניהול הוצאות 2026", layout="centered")

# מיפוי קטגוריות לדוגמה (יש לעדכן לפי גיליון העזר שלך)
CATEGORIES_MAP = {
    "מזון וצריכה": "משותפת",
    "מסעדות, קפה וברים": "משותפת",
    "דלק, חשמל וגז": "משותפת",
    "דברים לבית": "משותפת",
    "חיות מחמד": "משותפת",
    "עישונים": "פרטית",
    "ביגוד והנעלה": "פרטית",
    "פנאי ובידור": "פרטית",
    "תחבורה ורכבים": "פרטית"
}
ALL_CATEGORIES = list(CATEGORIES_MAP.keys())

# --- פונקציות חיבור ל-API ---
@st.cache_resource
def init_google_sheets():
    # קריאת הרשאות מתוך st.secrets
    credentials_dict = st.secrets["gcp_service_account"]
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(creds)
    # יש להחליף את ה-ID ב-ID האמיתי של קובץ "הוצאות 2026" שלך
    return client.open_by_key(st.secrets["spreadsheet_id"])

def parse_transactions_with_gemini(raw_text):
    genai.configure(api_key=st.secrets["gemini_api_key"])
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    You are a financial assistant. I will provide raw text from an Israeli credit card statement.
    Extract each transaction. 
    Available categories: {ALL_CATEGORIES}.
    Return a valid JSON array of objects. Each object must have exactly these keys:
    "date" (DD/MM/YYYY), "business" (string), "amount" (number), "suggested_category" (best match from available), "other_suggestions" (list of 2 other possible categories).
    Raw text:
    {raw_text}
    """
    
    response = model.generate_content(prompt)
    try:
        # חילוץ ה-JSON מתוך התשובה של Gemini
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(json_str)
    except Exception as e:
        st.error("שגיאה בפענוח נתוני Gemini. ודא שהקובץ תקין.")
        return []

# --- ניהול State ---
if 'transactions' not in st.session_state:
    st.session_state.transactions = []
if 'current_index' not in st.session_state:
    st.session_state.current_index = 0
if 'approved_data' not in st.session_state:
    st.session_state.approved_data = []
if 'payer' not in st.session_state:
    st.session_state.payer = "שגיב"

# --- ממשק משתמש ---
st.title("💸 ניהול הוצאות חכם")

# שלב 1: טעינת נתונים
if not st.session_state.transactions and len(st.session_state.approved_data) == 0:
    st.session_state.payer = st.radio("של מי פירוט האשראי?", ["שגיב", "הדר"])
    uploaded_file = st.file_uploader("גרור קובץ אשראי (Excel/CSV)", type=["csv", "xlsx"])
    
    if uploaded_file and st.button("נתח קובץ"):
        with st.spinner("מנתח נתונים בעזרת AI..."):
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            raw_data_str = df.to_string(index=False)
            parsed_data = parse_transactions_with_gemini(raw_data_str)
            
            if parsed_data:
                st.session_state.transactions = parsed_data
                st.rerun()

# שלב 2: כרטיסיות (Swipe)
elif st.session_state.current_index < len(st.session_state.transactions):
    st.progress(st.session_state.current_index / len(st.session_state.transactions))
    
    current_tx = st.session_state.transactions[st.session_state.current_index]
    
    st.subheader(f"עסקה {st.session_state.current_index + 1} מתוך {len(st.session_state.transactions)}")
    
    # בחירת קטגוריה
    col1, col2 = st.columns([2, 1])
    with col1:
        options = [current_tx["suggested_category"]] + current_tx["other_suggestions"]
        # הוספת כל שאר הקטגוריות למקרה שההמלצות שגויות
        options += [c for c in ALL_CATEGORIES if c not in options]
        selected_cat = st.selectbox("בחר קטגוריה:", options, key=f"cat_{st.session_state.current_index}")
    
    # קביעת צבע המסגרת
    is_shared = CATEGORIES_MAP.get(selected_cat) == "משותפת"
    border_color = "#3498db" if is_shared else "#e74c3c" # כחול למשותף, אדום לפרטי
    type_label = "משותפת" if is_shared else "פרטית"
    
    # הצגת הכרטיס
    st.markdown(f"""
        <div style="border: 3px solid {border_color}; border-radius: 10px; padding: 20px; text-align: center; margin-bottom: 20px; background-color: #f9f9f9;">
            <h4 style="color: #333; margin:0;">{current_tx['business']}</h4>
            <p style="color: #777; margin:0;">{current_tx['date']}</p>
            <h2 style="color: #333; margin: 10px 0;">₪{current_tx['amount']}</h2>
            <span style="background-color: {border_color}; color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px;">הוצאה {type_label}</span>
        </div>
    """, unsafe_allow_html=True)

    if st.button("אישור והבא ➔", use_container_width=True):
        st.session_state.approved_data.append({
            "תאריך": current_tx["date"],
            "בית עסק": current_tx["business"],
            "סכום": current_tx["amount"],
            "קטגוריה": selected_cat,
            "סוג": type_label,
            "משלם": st.session_state.payer
        })
        st.session_state.current_index += 1
        st.rerun()

# שלב 3: תובנות וכתיבה לדרייב
else:
    st.success("✅ סיימת לעבור על כל העסקאות!")
    
    df_approved = pd.DataFrame(st.session_state.approved_data)
    
    # תובנות מהירות
    total_amount = df_approved['סכום'].sum()
    shared_amount = df_approved[df_approved['סוג'] == 'משותפת']['סכום'].sum()
    
    col1, col2 = st.columns(2)
    col1.metric("סה\"כ הוצאות חודש זה", f"₪{total_amount:.2f}")
    col2.metric("מתוכן הוצאות משותפות", f"₪{shared_amount:.2f}")
    
    st.subheader("פילוח הוצאות משותפות")
    shared_df = df_approved[df_approved['סוג'] == 'משותפת']
    if not shared_df.empty:
        st.bar_chart(shared_df.groupby('קטגוריה')['סכום'].sum())
    
    if st.button("עדכן את הוצאות 2026 בדרייב 💾", type="primary", use_container_width=True):
        try:
            with st.spinner("כותב נתונים לדרייב..."):
                sheet_name = "תשלומים שגיב" if st.session_state.payer == "שגיב" else "תשלומים הדר"
                sh = init_google_sheets()
                worksheet = sh.worksheet(sheet_name)
                
                # הכנת הנתונים להזרקה (יש להתאים את סדר העמודות לאקסל שלך)
                rows_to_insert = []
                for _, row in df_approved.iterrows():
                    # הנחה: עמודה A=תאריך, B=בית עסק, C=קטגוריה, D=סכום
                    rows_to_insert.append([row["תאריך"], row["בית עסק"], row["קטגוריה"], row["סכום"]])
                
                worksheet.append_rows(rows_to_insert)
                st.success("הנתונים עודכנו בהצלחה! האקסל יבצע את שאר הקיזוזים.")
                
                # איפוס המערכת לקובץ הבא
                st.session_state.transactions = []
                st.session_state.current_index = 0
                st.session_state.approved_data = []
        except Exception as e:
            st.error(f"שגיאה בכתיבה לדרייב: {e}")
