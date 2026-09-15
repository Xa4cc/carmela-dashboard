"""
Dashboard Carmela Guemes - app de Streamlit (Etapa 1)
-------------------------------------------------------
Corre localmente. Sube los CSV de ventas y productos a mano,
la app hace el mismo analisis que analizar_carmela.py pero con
graficos interactivos en vez de un JSON.

Como correrla:
    pip install streamlit pandas numpy
    streamlit run app.py

Etapa 2 (siguiente paso, no incluido aca): desplegar esto en
share.streamlit.io conectando un repo de GitHub, para tener un
link publico en vez de correrlo en tu compu.
"""
import os
import pandas as pd
import streamlit as st

from analizar_carmela import (
    cargar_ventas,
    cargar_productos,
    cargar_mercadolibre,
    metricas_ventana,
    metricas_historicas,
    chequeo_stock,
    recurrencia_del_periodo,
    dias_hasta_segunda_compra,
    cancelaciones_por_medio_pago,
    cancelaciones_por_provincia,
    stock_nunca_vendido,
    metricas_canal_tn,
    metricas_canal_ml,
)

HISTORIAL_PATH = "historial_cortes.csv"

st.set_page_config(page_title="Dashboard Carmela Güemes", page_icon="👜", layout="wide")


def chequear_password():
    """Muestra un campo de contraseña y frena la app hasta que sea correcta.
    La contraseña real vive en Secrets (nunca en el código), asi que no queda
    expuesta aunque el repo de GitHub sea público."""
    if st.session_state.get("autenticado"):
        return True

    st.title("👜 Dashboard Carmela Güemes")
    st.caption("Ingresá la contraseña para ver el dashboard.")
    clave = st.text_input("Contraseña", type="password")

    if not clave:
        st.stop()

    esperada = st.secrets.get("password")
    if esperada is None:
        st.error(
            "No hay contraseña configurada todavía. Creá un archivo "
            "`.streamlit/secrets.toml` local con `password = \"tu-clave\"` "
            "(para probar en tu compu), y agregá el mismo valor en "
            "Settings → Secrets de la app en Streamlit Cloud (para el link público)."
        )
        st.stop()

    if clave == esperada:
        st.session_state["autenticado"] = True
        st.rerun()
    else:
        st.error("Contraseña incorrecta.")
        st.stop()


chequear_password()

st.title("👜 Dashboard Carmela Güemes")
st.caption("Etapa 1: corre local, todavía subís los CSV a mano — sin conexión a la API todavía.")

# ---------- Carga de archivos ----------
col1, col2, col3 = st.columns(3)
with col1:
    archivo_ventas = st.file_uploader("Export de ventas Tiendanube (CSV)", type="csv")
with col2:
    archivo_productos = st.file_uploader("Export de productos Tiendanube (CSV)", type="csv")
with col3:
    archivo_ml = st.file_uploader("Export de ventas Mercado Libre (Excel, opcional)", type="xlsx")

dias_ventana = st.sidebar.slider("Ventana de días para el corte", min_value=7, max_value=90, value=30, step=1)

if not archivo_ventas or not archivo_productos:
    st.info("Subí los dos archivos de Tiendanube para ver el análisis. El de Mercado Libre es opcional.")
    st.stop()

# ---------- Procesamiento ----------
# cargar_ventas/cargar_productos esperan una ruta de archivo; los uploads de
# Streamlit son objetos en memoria, pandas los acepta igual sin problema.
df_ventas = cargar_ventas(archivo_ventas)
df_productos = cargar_productos(archivo_productos)
paid = df_ventas[df_ventas['Estado del pago'] == 'Recibido'].copy()

ventana = metricas_ventana(paid, dias_ventana)
historico = metricas_historicas(paid)
riesgo = chequeo_stock(paid, df_productos, dias_ventana)
recurrencia_periodo = recurrencia_del_periodo(paid, dias_ventana)
dias_2da_compra = dias_hasta_segunda_compra(paid)
cancel_medio_pago = cancelaciones_por_medio_pago(df_ventas)
cancel_provincia = cancelaciones_por_provincia(df_ventas)
stock_muerto = stock_nunca_vendido(paid, df_productos)

canal_ml = None
if archivo_ml:
    try:
        df_ml = cargar_mercadolibre(archivo_ml)
        canal_ml = metricas_canal_ml(df_ml, dias_ventana)
    except Exception as e:
        st.warning(f"No se pudo leer el archivo de Mercado Libre: {e}")
canal_tn = metricas_canal_tn(df_ventas, paid, dias_ventana)

# ---------- Tabs ----------
tab_resumen, tab_tendencia, tab_productos, tab_canales, tab_hallazgos = st.tabs(
    ["📊 Resumen del mes", "📈 Tendencia", "🛍️ Productos", "🔀 Canales", "🔍 Hallazgos clave"]
)

with tab_resumen:
    orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

    def dow_chart_df(promedio_dict):
        d = pd.DataFrame({
            'día': list(promedio_dict.keys()),
            'pedidos_promedio': list(promedio_dict.values()),
        })
        d['día'] = pd.Categorical(d['día'], categories=orden_dias, ordered=True)
        return d.sort_values('día').set_index('día')

    if canal_ml is not None:
        st.subheader("Negocio total (Tiendanube + Mercado Libre)")
        t1, t2, t3, t4 = st.columns(4)
        total_pedidos = canal_tn['pedidos'] + canal_ml['pedidos']
        total_bruto = canal_tn['ingresos_brutos'] + canal_ml['ingresos_brutos']
        total_neto = canal_tn['ingresos_netos'] + canal_ml['ingresos_netos']
        t1.metric("Pedidos totales", total_pedidos)
        t2.metric("Unidades vendidas", canal_tn['unidades'] + canal_ml['unidades'])
        t3.metric("Ingresos brutos", f"${total_bruto:,.0f}")
        t4.metric("Ingresos netos", f"${total_neto:,.0f}")
        st.divider()

        col_tn, col_ml = st.columns(2)
        with col_tn:
            st.markdown("#### 🛒 Tiendanube")
            st.metric("Pedidos", ventana['pedidos'])
            st.metric("Ticket promedio", f"${ventana['ticket_promedio']:,.0f}")
            st.metric("Día más fuerte", ventana['dia_pico'])
            st.metric("% AMBA", f"{ventana['pct_amba']}%")
            st.caption("Pedidos por día")
            st.bar_chart(dow_chart_df(canal_tn['promedio_por_dia_semana']))
        with col_ml:
            st.markdown("#### 🟡 Mercado Libre")
            st.metric("Pedidos", canal_ml['pedidos'])
            st.metric("Ticket promedio", f"${round(canal_ml['ingresos_brutos']/canal_ml['pedidos']):,.0f}" if canal_ml['pedidos'] else "—")
            st.metric("Día más fuerte", canal_ml['dia_pico'])
            st.metric("% cancelación", f"{canal_ml['pct_cancelacion']}%")
            st.caption("Pedidos por día")
            st.bar_chart(dow_chart_df(canal_ml['promedio_por_dia_semana']))

    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pedidos (Tiendanube)", ventana['pedidos'])
        c2.metric("Ticket promedio", f"${ventana['ticket_promedio']:,.0f}")
        c3.metric("Día más fuerte", ventana['dia_pico'])
        c4.metric("% AMBA", f"{ventana['pct_amba']}%")
        st.subheader("Pedidos por día de la semana")
        st.bar_chart(dow_chart_df(ventana['promedio_por_dia_semana']))
        st.caption("Subí el archivo de Mercado Libre arriba para ver el desglose por canal.")

    st.divider()
    st.subheader("Riesgo de quiebre de stock (Tiendanube)")
    if riesgo:
        st.dataframe(pd.DataFrame(riesgo), use_container_width=True)
    else:
        st.write("No hay productos con stock bajo y venta activa en esta ventana.")

with tab_tendencia:
    st.subheader("Historial de cortes")
    nueva_fila = pd.DataFrame([{
        'fecha_corte': ventana['fecha_corte'],
        'rango': ventana['rango'],
        'pedidos': ventana['pedidos'],
        'ticket_promedio': ventana['ticket_promedio'],
        'pct_recurrencia_periodo': recurrencia_periodo,
        'pct_amba': ventana['pct_amba'],
    }])

    if os.path.exists(HISTORIAL_PATH):
        historial_df = pd.read_csv(HISTORIAL_PATH)
    else:
        historial_df = pd.DataFrame(columns=nueva_fila.columns)

    st.dataframe(historial_df, use_container_width=True)

    if st.button("💾 Guardar este corte al historial"):
        historial_df = pd.concat([historial_df, nueva_fila], ignore_index=True)
        historial_df.to_csv(HISTORIAL_PATH, index=False)
        st.success("Corte guardado. Recargá la página para verlo reflejado en los gráficos de abajo.")

    if len(historial_df) >= 2:
        st.subheader("Ticket promedio en el tiempo")
        st.line_chart(historial_df.set_index('rango')['ticket_promedio'])
        st.subheader("% Recurrencia (del período) en el tiempo")
        st.line_chart(historial_df.set_index('rango')['pct_recurrencia_periodo'])
    else:
        st.caption("Guardá al menos 2 cortes para ver los gráficos de tendencia.")

    st.caption(
        "⚠️ Esto se guarda en un archivo local (historial_cortes.csv). "
        "Si más adelante desplegás la app en Streamlit Cloud, ese archivo no "
        "persiste entre reinicios — ahí conviene pasar a Google Sheets (Etapa 4)."
    )

with tab_productos:
    st.subheader(f"Top productos por ingresos ({ventana['rango']})")
    top_df = pd.DataFrame(ventana['top_productos'])
    # preservar el orden de mayor a menor ingreso (evita que el grafico ordene alfabetico solo)
    orden_productos = top_df['Nombre del producto'].tolist()
    top_df['Nombre del producto'] = pd.Categorical(
        top_df['Nombre del producto'], categories=orden_productos, ordered=True
    )
    top_df = top_df.set_index('Nombre del producto')
    st.bar_chart(top_df['ingresos'])
    st.dataframe(top_df, use_container_width=True)

    st.subheader("Segmentación por método de pago (histórico completo)")
    cuotas_df = pd.DataFrame(historico['segmentacion_cuotas']).T
    st.dataframe(cuotas_df, use_container_width=True)

with tab_canales:
    if canal_ml is None:
        st.info("Subí el export de Mercado Libre arriba para ver la comparación de canales.")
    else:
        tabla_canales = pd.DataFrame({
            'Tiendanube': {
                'Pedidos': canal_tn['pedidos'],
                'Ingresos brutos': canal_tn['ingresos_brutos'],
                'Ingresos netos': canal_tn['ingresos_netos'],
                'Comisión/costo total': canal_tn['comision_total'],
                '% que se lleva la plataforma': canal_tn['pct_comision'],
                '% cancelación': canal_tn['pct_cancelacion'],
            },
            'Mercado Libre': {
                'Pedidos': canal_ml['pedidos'],
                'Ingresos brutos': canal_ml['ingresos_brutos'],
                'Ingresos netos': canal_ml['ingresos_netos'],
                'Comisión/costo total': canal_ml['comision_total'],
                '% que se lleva la plataforma': canal_ml['pct_comision'],
                '% cancelación': canal_ml['pct_cancelacion'],
            },
        })
        st.dataframe(tabla_canales, use_container_width=True)

        total_bruto = canal_tn['ingresos_brutos'] + canal_ml['ingresos_brutos']
        c1, c2, c3 = st.columns(3)
        c1.metric("% del negocio (bruto) que es Mercado Libre",
                   f"{round(100*canal_ml['ingresos_brutos']/total_bruto,1)}%")
        c2.metric("Diferencia de comisión (Mercado Libre vs Tiendanube)",
                   f"{round(canal_ml['pct_comision'] - canal_tn['pct_comision'],1)} pp")
        c3.metric("Plata que se lleva Mercado Libre este período",
                   f"${canal_ml['comision_total']:,.0f}")

        st.caption(
            "Ingresos brutos = lo que paga el cliente. Ingresos netos = lo que "
            "efectivamente queda después de comisiones/costos de cada plataforma "
            "(no incluye costo de mercadería, que depende de que se cargue el costo por producto)."
        )

with tab_hallazgos:
    c1, c2 = st.columns(2)
    c1.metric("% recurrencia histórica (todos los clientes)", f"{historico['pct_recurrentes']}%")
    c2.metric(f"% de compradores de los últimos {dias_ventana} días que ya eran clientes", f"{recurrencia_periodo}%")

    if dias_2da_compra['dias_promedio'] is not None:
        st.metric(
            "Días promedio hasta la 2da compra",
            f"{dias_2da_compra['dias_promedio']} días",
            help=f"Calculado sobre {dias_2da_compra['casos']} clientes que volvieron a comprar."
        )

    st.subheader("Recurrencia por segmento de método de pago")
    st.dataframe(pd.DataFrame(historico['segmentacion_cuotas']).T, use_container_width=True)

    st.subheader("Cancelaciones por medio de pago")
    st.dataframe(pd.DataFrame(cancel_medio_pago), use_container_width=True)

    st.subheader("Cancelaciones por provincia (solo transferencia/link de pago)")
    st.dataframe(pd.DataFrame(cancel_provincia), use_container_width=True)

    st.subheader("Stock parado en productos que nunca vendieron")
    sm1, sm2 = st.columns(2)
    sm1.metric("Total en productos sin ninguna venta", f"${stock_muerto['total_valor']:,.0f}")
    sm2.metric("De eso, solo por estar ocultos de la tienda", f"${stock_muerto['valor_oculto']:,.0f}")
    if stock_muerto['productos_ocultos']:
        st.caption("Arreglo gratis (activar \"Mostrar en tienda\"):")
        st.dataframe(pd.DataFrame(stock_muerto['productos_ocultos']), use_container_width=True)
    if stock_muerto['productos_visibles_sin_ventas']:
        st.caption("Visibles hace tiempo y aun así sin ventas (requieren revisión real):")
        st.dataframe(pd.DataFrame(stock_muerto['productos_visibles_sin_ventas']), use_container_width=True)

st.divider()
st.caption("Datos: exports de Tiendanube. No incluye ventas de otros canales fuera de Tiendanube.")
