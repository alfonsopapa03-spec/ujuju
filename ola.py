import streamlit as st
from supabase import create_client
import os

# Borra o comenta las líneas de dotenv si las tenías
# from dotenv import load_dotenv
# load_dotenv()

@st.cache_resource
def init_supabase():
    # Usamos st.secrets para obtener las llaves de forma segura
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

st.set_page_config(page_title="Inventario", page_icon="📦", layout="wide")

# ========================
# MANEJO DE SESIÓN
# ========================
if "session" not in st.session_state:
    st.session_state.session = None
if "user" not in st.session_state:
    st.session_state.user = None

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.session = res.session
        st.session_state.user = res.user
        # Importante: usar el token del usuario para que RLS funcione
        supabase.postgrest.auth(res.session.access_token)
        return True
    except Exception as e:
        st.error(f"Error al iniciar sesión: {e}")
        return False

def register(email, password):
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        st.success("✅ Cuenta creada. Revisa tu email para confirmar.")
    except Exception as e:
        st.error(f"Error al registrarse: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.session = None
    st.session_state.user = None
    st.rerun()

# ========================
# PANTALLA DE LOGIN
# ========================
if not st.session_state.session:
    st.title("📦 Gestión de Inventario")
    tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Contraseña", type="password", key="login_pass")
        if st.button("Entrar"):
            if login(email, password):
                st.rerun()

    with tab2:
        email_r = st.text_input("Email", key="reg_email")
        password_r = st.text_input("Contraseña", type="password", key="reg_pass")
        if st.button("Crear cuenta"):
            register(email_r, password_r)

    st.stop()  # No renderizar nada más si no está logueado

# ========================
# APP PRINCIPAL (autenticado)
# ========================

# Restaurar token en cada recarga de página
supabase.postgrest.auth(st.session_state.session.access_token)
user_id = st.session_state.user.id

st.sidebar.write(f"👤 {st.session_state.user.email}")
if st.sidebar.button("Cerrar sesión"):
    logout()

menu = st.sidebar.selectbox("Menú", ["Dashboard", "Productos", "Agregar Producto", "Registrar Movimiento"])
st.title("📦 Mi Inventario")

# ========================
# DASHBOARD
# ========================
if menu == "Dashboard":
    data = supabase.table("productos").select("*").execute().data
    df = pd.DataFrame(data)

    if df.empty:
        st.info("Aún no tienes productos. ¡Agrega el primero!")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Productos", len(df))
        col2.metric("Unidades Totales", df["cantidad"].sum())
        col3.metric("Valor Total", f"${(df['cantidad'] * df['precio']).sum():,.2f}")

        fig = px.bar(df.groupby("categoria")["cantidad"].sum().reset_index(),
                     x="categoria", y="cantidad", title="Stock por Categoría")
        st.plotly_chart(fig, use_container_width=True)

        stock_bajo = df[df["cantidad"] < 10]
        if not stock_bajo.empty:
            st.warning(f"⚠️ {len(stock_bajo)} productos con stock bajo")
            st.dataframe(stock_bajo[["nombre", "cantidad"]])

# ========================
# VER PRODUCTOS
# ========================
elif menu == "Productos":
    busqueda = st.text_input("🔍 Buscar")
    data = supabase.table("productos").select("*").execute().data
    df = pd.DataFrame(data)

    if busqueda and not df.empty:
        df = df[df["nombre"].str.contains(busqueda, case=False, na=False)]

    st.dataframe(df, use_container_width=True)

# ========================
# AGREGAR PRODUCTO
# ========================
elif menu == "Agregar Producto":
    with st.form("form_producto"):
        nombre = st.text_input("Nombre *")
        descripcion = st.text_area("Descripción")
        col1, col2 = st.columns(2)
        categoria = col1.selectbox("Categoría", ["Electrónica", "Alimentos", "Ropa", "Herramientas", "Otro"])
        unidad = col2.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "metro"])
        cantidad = st.number_input("Cantidad inicial", min_value=0)
        precio = st.number_input("Precio unitario", min_value=0.0, format="%.2f")

        if st.form_submit_button("💾 Guardar"):
            if nombre:
                supabase.table("productos").insert({
                    "nombre": nombre, "descripcion": descripcion,
                    "categoria": categoria, "unidad": unidad,
                    "cantidad": cantidad, "precio": precio,
                    "user_id": user_id  # 👈 clave para el aislamiento
                }).execute()
                st.success("✅ Producto guardado")
            else:
                st.error("El nombre es obligatorio")

# ========================
# REGISTRAR MOVIMIENTO
# ========================
elif menu == "Registrar Movimiento":
    productos = supabase.table("productos").select("id, nombre, cantidad").execute().data
    if not productos:
        st.info("No tienes productos aún.")
    else:
        nombres = {p["nombre"]: p for p in productos}
        with st.form("form_movimiento"):
            producto_sel = st.selectbox("Producto", list(nombres.keys()))
            tipo = st.radio("Tipo", ["entrada", "salida"], horizontal=True)
            cantidad = st.number_input("Cantidad", min_value=1, value=1)
            motivo = st.text_input("Motivo")

            if st.form_submit_button("📝 Registrar"):
                prod = nombres[producto_sel]
                nueva_cantidad = prod["cantidad"] + cantidad if tipo == "entrada" else prod["cantidad"] - cantidad

                if nueva_cantidad < 0:
                    st.error("❌ Stock insuficiente")
                else:
                    supabase.table("productos").update(
                        {"cantidad": nueva_cantidad}
                    ).eq("id", prod["id"]).execute()

                    supabase.table("movimientos").insert({
                        "producto_id": prod["id"], "tipo": tipo,
                        "cantidad": cantidad, "motivo": motivo,
                        "user_id": user_id  # 👈 también aquí
                    }).execute()
                    st.success(f"✅ Nuevo stock: {nueva_cantidad}")
import streamlit as st
from supabase import create_client, Client

# 1. Instalación (asegúrate de hacer: pip install supabase)

# 2. Inicializar la conexión usando los secretos
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# 3. Ejemplo de cómo guardar un producto vinculado al usuario actual
def guardar_producto(nombre, cantidad):
    # Obtenemos el ID del usuario que inició sesión
    user = supabase.auth.get_user()
    if user:
        user_id = user.user.id
        data = {
            "nombre": nombre,
            "cantidad": cantidad,
            "user_id": user_id  # Importante para que el RLS funcione
        }
        res = supabase.table("inventario").insert(data).execute()
        return res

# 4. Ejemplo de cómo leer (Supabase filtrará automáticamente por el RLS)
def leer_inventario():
    res = supabase.table("inventario").select("*").execute()
    return res.data
