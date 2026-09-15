"""
Analisis mensual Carmela Guemes
--------------------------------
Lee los exports crudos de Tiendanube (ventas.csv y productos.csv) y calcula
todas las metricas estandar del reporte mensual + tracker, sin pasar por
DB Browser / SQL manual.

Uso:
    python3 analizar_carmela.py ruta_ventas.csv ruta_productos.csv [--dias 30]
"""
import sys
import json
import re
import argparse
import pandas as pd
import numpy as np


def cargar_ventas(path):
    df = pd.read_csv(path, sep=';', encoding='latin-1')
    df['fecha_dt'] = pd.to_datetime(df['Fecha'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
    df['Total'] = pd.to_numeric(df['Total'].astype(str).str.replace(',', '', regex=False), errors='coerce')
    df['cuotas_num'] = pd.to_numeric(df['Cantidad de cuotas'], errors='coerce')
    return df


def cargar_productos(path):
    df = pd.read_csv(path, sep=';', encoding='latin-1')
    df['precio_num'] = pd.to_numeric(
        df['Precio'].astype(str).str.replace(',', '', regex=False), errors='coerce'
    )
    return df


def nombre_fill_productos(df_prod):
    """Rellena 'Nombre' (solo viene en la primera fila de cada grupo de variantes)
    y agrega stock total + precio por Identificador de URL."""
    g = df_prod.groupby('Identificador de URL').agg(
        nombre_producto=('Nombre', lambda s: s.dropna().iloc[0] if s.notna().any() else None),
        stock_total=('Stock (Showroom Carmela Güemes)', 'sum'),
        precio=('precio_num', 'max'),
        mostrar_en_tienda=('Mostrar en tienda', 'max'),
    ).reset_index()
    return g


DOW_MAP = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}


def promedio_por_dia_semana(fechas, min_fecha, max_fecha):
    """Dado un Series de fechas (una por pedido/venta), calcula el promedio de
    pedidos por dia de la semana corrigiendo por cuantas veces aparece cada
    dia en la ventana (ej: si hay 5 sabados y solo 4 lunes)."""
    conteo_dias = fechas.dt.dayofweek.value_counts()
    todas_fechas = pd.date_range(min_fecha, max_fecha, freq='D')
    ocurrencias = pd.Series([d.dayofweek for d in todas_fechas]).value_counts()
    promedio_dow = (conteo_dias / ocurrencias).reindex(range(7)).rename(index=DOW_MAP)
    dia_pico = promedio_dow.idxmax()
    return promedio_dow.round(1).to_dict(), dia_pico


def metricas_ventana(paid, dias, offset_dias=0):
    """Metricas del reporte mensual sobre los ultimos N dias.
    offset_dias > 0 corre la ventana hacia atras (para comparar contra un
    periodo anterior de la misma duracion)."""
    max_fecha = paid['fecha_dt'].dt.normalize().max() - pd.Timedelta(days=offset_dias)
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)
    ventana = paid[
        (paid['fecha_dt'].dt.normalize() >= min_fecha) & (paid['fecha_dt'].dt.normalize() <= max_fecha)
    ].copy()

    pedidos_unicos = ventana.drop_duplicates('Número de orden')
    n_pedidos = len(pedidos_unicos)
    ticket_promedio = pedidos_unicos['Total'].mean()

    # top productos por ingresos
    ventana['ingreso_item'] = ventana['Cantidad del producto'] * ventana['Precio del producto']
    top_productos = (
        ventana.groupby('Nombre del producto')
        .agg(unidades=('Cantidad del producto', 'sum'), ingresos=('ingreso_item', 'sum'))
        .sort_values('ingresos', ascending=False)
        .head(8)
    )

    promedio_dow, dia_pico = promedio_por_dia_semana(pedidos_unicos['fecha_dt'], min_fecha, max_fecha)

    # AMBA %
    amba_provincias = ['Buenos Aires', 'Capital Federal', 'Gran Buenos Aires']
    pct_amba = 100 * pedidos_unicos['Provincia o estado'].isin(amba_provincias).mean()

    return {
        'rango': f"Últimos {dias} días ({min_fecha.date()} a {max_fecha.date()})",
        'fecha_corte': str(max_fecha.date()),
        'pedidos': int(n_pedidos),
        'ticket_promedio': round(ticket_promedio),
        'top_productos': top_productos.reset_index().to_dict('records'),
        'promedio_por_dia_semana': promedio_dow,
        'dia_pico': dia_pico,
        'pct_amba': round(pct_amba, 1),
    }


def metricas_historicas(paid):
    """Metricas que se calculan sobre TODO el historial (no solo la ventana reciente)."""
    pedidos_unicos = paid.drop_duplicates('Número de orden').copy()

    por_cliente = pedidos_unicos.groupby('Email').size()
    pct_recurrentes = 100 * (por_cliente > 1).mean()

    # segmentacion por cuotas
    pedidos_unicos['es_cuotas'] = pedidos_unicos['cuotas_num'].fillna(0) >= 2
    seg = pedidos_unicos.groupby('Email')['es_cuotas'].agg(['sum', 'count'])
    seg['segmento'] = np.select(
        [seg['sum'] == seg['count'], seg['sum'] == 0],
        ['Solo cuotas', 'Nunca cuotas'],
        default='Mezcla',
    )
    ingresos_totales = pedidos_unicos['Total'].sum()
    resumen_cuotas = {}
    for s in ['Solo cuotas', 'Nunca cuotas', 'Mezcla']:
        emails = seg[seg['segmento'] == s].index
        sub = pedidos_unicos[pedidos_unicos['Email'].isin(emails)]
        pedidos_por_cliente_seg = sub.groupby('Email').size()
        resumen_cuotas[s] = {
            'clientes': int(len(emails)),
            'ingresos': round(sub['Total'].sum()),
            'pct_ingresos': round(100 * sub['Total'].sum() / ingresos_totales, 1),
            'ticket_promedio': round(sub['Total'].mean()) if len(sub) else 0,
            'pct_recurrentes': round(100 * (pedidos_por_cliente_seg > 1).mean(), 1) if len(pedidos_por_cliente_seg) else 0,
        }

    return {
        'total_clientes': int(len(por_cliente)),
        'pct_recurrentes': round(pct_recurrentes, 1),
        'segmentacion_cuotas': resumen_cuotas,
    }


MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}


def _parse_fecha_ml(texto):
    """Convierte '1 de abril de 2026 15:35 hs.' a Timestamp."""
    m = re.match(r'(\d+) de (\w+) de (\d+)', str(texto))
    if not m:
        return pd.NaT
    dia, mes, anio = m.groups()
    mes_num = MESES_ES.get(mes.lower())
    if mes_num is None:
        return pd.NaT
    return pd.Timestamp(year=int(anio), month=mes_num, day=int(dia))


def cargar_mercadolibre(path):
    """Carga el export de 'Ventas AR' de Mercado Libre. El archivo trae un
    bloque de texto introductorio antes del header real (fila 6)."""
    df = pd.read_excel(path, sheet_name='Ventas AR', header=5)
    df['fecha_dt'] = df['Fecha de venta'].apply(_parse_fecha_ml)
    for col in ['Ingresos por productos (ARS)', 'Cargo por venta', 'Costo fijo',
                'Costo por ofrecer cuotas', 'Total (ARS)']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def metricas_canal_ml(df_ml, dias, offset_dias=0):
    max_fecha = df_ml['fecha_dt'].dt.normalize().max() - pd.Timedelta(days=offset_dias)
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)
    ventana = df_ml[
        (df_ml['fecha_dt'].dt.normalize() >= min_fecha) & (df_ml['fecha_dt'].dt.normalize() <= max_fecha)
    ]
    bruto = ventana['Ingresos por productos (ARS)'].sum()
    neto = ventana['Total (ARS)'].sum()
    comision = -ventana['Cargo por venta'].fillna(0).sum()  # viene negativo en el archivo
    canceladas = ventana['Estado'].astype(str).str.contains('Cancel', case=False, na=False).sum()
    promedio_dow, dia_pico = promedio_por_dia_semana(ventana['fecha_dt'], min_fecha, max_fecha)
    return {
        'unidades': int(ventana['Unidades'].sum()),
        'pedidos': int(len(ventana)),
        'ingresos_brutos': round(bruto),
        'ingresos_netos': round(neto),
        'comision_total': round(comision),
        'pct_comision': round(100 * comision / bruto, 1) if bruto else 0,
        'pct_cancelacion': round(100 * canceladas / len(ventana), 1) if len(ventana) else 0,
        'promedio_por_dia_semana': promedio_dow,
        'dia_pico': dia_pico,
    }


def metricas_canal_tn(df_ventas, paid, dias, offset_dias=0):
    pedidos_all = df_ventas.drop_duplicates('Número de orden').copy()
    pedidos_pagados = paid.drop_duplicates('Número de orden').copy()
    max_fecha = pedidos_pagados['fecha_dt'].dt.normalize().max() - pd.Timedelta(days=offset_dias)
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)
    en_rango = lambda s: (s.dt.normalize() >= min_fecha) & (s.dt.normalize() <= max_fecha)
    ventana = pedidos_pagados[en_rango(pedidos_pagados['fecha_dt'])]
    ventana_all = pedidos_all[en_rango(pedidos_all['fecha_dt'])]
    ventana_items = paid[en_rango(paid['fecha_dt'])]
    bruto = ventana['Total'].sum()
    costo_proc = ventana['Costo de procesamiento'].fillna(0).sum()
    canceladas = (ventana_all['Estado de la orden'] == 'Cancelada').sum()
    promedio_dow, dia_pico = promedio_por_dia_semana(ventana['fecha_dt'], min_fecha, max_fecha)
    return {
        'pedidos': int(len(ventana)),
        'unidades': int(ventana_items['Cantidad del producto'].sum()),
        'ingresos_brutos': round(bruto),
        'ingresos_netos': round(bruto - costo_proc),
        'comision_total': round(costo_proc),
        'pct_comision': round(100 * costo_proc / bruto, 1) if bruto else 0,
        'pct_cancelacion': round(100 * canceladas / len(ventana_all), 1) if len(ventana_all) else 0,
        'promedio_por_dia_semana': promedio_dow,
        'dia_pico': dia_pico,
    }


def recurrencia_del_periodo(paid, dias):
    """De la gente que compro en la ventana reciente, que % ya era cliente de antes.
    Es una metrica mas sensible a cambios recientes que el pct_recurrentes historico."""
    max_fecha = paid['fecha_dt'].dt.normalize().max()
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)
    compradores_ventana = set(paid[paid['fecha_dt'].dt.normalize() >= min_fecha]['Email'].unique())
    historial = paid.drop_duplicates('Número de orden').groupby('Email').size()
    ya_eran = sum(1 for e in compradores_ventana if historial.get(e, 0) > 1)
    return round(100 * ya_eran / len(compradores_ventana), 1) if compradores_ventana else 0.0


def dias_hasta_segunda_compra(paid):
    """Promedio de dias entre la 1ra y 2da compra de cada cliente (equivalente a
    la consulta SQL con LAG()/ROW_NUMBER() que usamos en DB Browser).
    Se colapsa primero a un registro por (Email, fecha) para no contar dos pedidos
    del mismo dia como si fueran una "segunda compra" separada."""
    pedidos = paid[['Email', 'fecha_dt']].copy()
    pedidos['fecha'] = pedidos['fecha_dt'].dt.normalize()
    pedidos = pedidos.drop_duplicates(['Email', 'fecha']).sort_values(['Email', 'fecha'])
    pedidos['n_compra'] = pedidos.groupby('Email').cumcount() + 1
    pedidos['fecha_anterior'] = pedidos.groupby('Email')['fecha'].shift(1)
    segunda = pedidos[pedidos['n_compra'] == 2].copy()
    if segunda.empty:
        return {'dias_promedio': None, 'casos': 0}
    segunda['dias'] = (segunda['fecha'] - segunda['fecha_anterior']).dt.days
    return {'dias_promedio': round(segunda['dias'].mean()), 'casos': int(len(segunda))}


def cancelaciones_por_medio_pago(df_ventas):
    """Tasa de cancelacion por medio de pago, sobre TODOS los pedidos (no solo pagados),
    igual que la consulta SQL original."""
    pedidos = df_ventas.drop_duplicates('Número de orden')[['Medio de pago', 'Estado de la orden']].copy()
    resumen = pedidos.groupby('Medio de pago').agg(
        pedidos_totales=('Estado de la orden', 'count'),
        cancelados=('Estado de la orden', lambda s: (s == 'Cancelada').sum()),
    )
    resumen['pct_cancelacion'] = (100 * resumen['cancelados'] / resumen['pedidos_totales']).round(1)
    resumen = resumen[resumen['pedidos_totales'] >= 10].sort_values('pct_cancelacion', ascending=False)
    return resumen.reset_index().to_dict('records')


def cancelaciones_por_provincia(df_ventas, medios_friccion=('Transferencia o depósito bancario', 'LINK DE PAGO')):
    """Tasa de cancelacion por provincia, filtrando solo a metodos de pago con friccion
    (transferencia/link) para que la comparacion entre provincias sea justa."""
    pedidos = df_ventas.drop_duplicates('Número de orden')[
        ['Provincia o estado', 'Estado de la orden', 'Medio de pago']
    ].copy()
    pedidos = pedidos[pedidos['Medio de pago'].isin(medios_friccion)]
    resumen = pedidos.groupby('Provincia o estado').agg(
        pedidos=('Estado de la orden', 'count'),
        cancelados=('Estado de la orden', lambda s: (s == 'Cancelada').sum()),
    )
    resumen['pct_cancelacion'] = (100 * resumen['cancelados'] / resumen['pedidos']).round(1)
    resumen = resumen[resumen['pedidos'] >= 20].sort_values('pct_cancelacion', ascending=False)
    return resumen.reset_index().to_dict('records')


def stock_nunca_vendido(paid, df_prod):
    """Productos con stock actual que nunca registraron ni una venta en todo el historial,
    separando los que estan ocultos de la tienda (arreglo gratis) de los que si son visibles."""
    prod = nombre_fill_productos(df_prod)
    vendidos_alguna_vez = set(paid['Nombre del producto'].unique())
    nunca_vendidos = prod[
        (prod['stock_total'] > 0) & (~prod['nombre_producto'].isin(vendidos_alguna_vez))
    ].copy()
    nunca_vendidos['valor_stock'] = nunca_vendidos['stock_total'] * nunca_vendidos['precio']
    ocultos = nunca_vendidos[nunca_vendidos['mostrar_en_tienda'].astype(str).str.upper() != 'SI']
    visibles = nunca_vendidos[nunca_vendidos['mostrar_en_tienda'].astype(str).str.upper() == 'SI']
    return {
        'total_valor': round(nunca_vendidos['valor_stock'].sum()),
        'total_productos': int(len(nunca_vendidos)),
        'valor_oculto': round(ocultos['valor_stock'].sum()),
        'productos_ocultos': ocultos[['nombre_producto', 'stock_total', 'valor_stock']].round(0).to_dict('records'),
        'valor_visible_sin_ventas': round(visibles['valor_stock'].sum()),
        'productos_visibles_sin_ventas': visibles[['nombre_producto', 'stock_total', 'valor_stock']].round(0).to_dict('records'),
    }


def chequeo_stock(paid, df_prod, dias=30):
    """Cruza ventas recientes contra stock actual para alertar quiebres."""
    prod = nombre_fill_productos(df_prod)
    max_fecha = paid['fecha_dt'].dt.normalize().max()
    ventana = paid[paid['fecha_dt'].dt.normalize() >= max_fecha - pd.Timedelta(days=dias - 1)]
    venta_producto = ventana.groupby('Nombre del producto')['Cantidad del producto'].sum() / dias

    prod = prod.merge(
        venta_producto.rename('venta_diaria'), left_on='nombre_producto', right_index=True, how='left'
    )
    prod['venta_diaria'] = prod['venta_diaria'].fillna(0)
    riesgo = prod[(prod['stock_total'] > 0) & (prod['venta_diaria'] > 0)].copy()
    riesgo['dias_de_stock'] = riesgo['stock_total'] / riesgo['venta_diaria']
    riesgo = riesgo.sort_values('dias_de_stock').head(10)

    return riesgo[['nombre_producto', 'stock_total', 'venta_diaria', 'dias_de_stock']].round(1).to_dict('records')


STOP_WORDS_MODELO = {'de', 'color', 'tote', 'bag', 'cuero', 'la', 'el', 'y', 'con', 'en', 'a'}


def _norm_modelo(s):
    s = str(s).lower()
    s = s.replace('maxibilletera', 'maxi billetera')  # arregla el nombre compuesto del archivo de costos
    s = re.sub(r'[^a-záéíóúñ0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def cargar_costos(path):
    """Carga el archivo de costos por modelo (lo arma el dueño del negocio a mano,
    formato libre: columnas de moneda como texto '$44,202.00')."""
    df = pd.read_csv(path, sep=None, engine='python', encoding='latin-1')
    df['Modelo'] = df['Modelo'].astype(str).str.replace('\xa0', ' ', regex=False).str.strip()
    for col in df.columns[1:]:
        df[col] = (
            df[col].astype(str).str.replace('$', '', regex=False)
            .str.replace(',', '', regex=False).str.strip()
        )
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def asignar_modelos(df_ventas, costos):
    """Para cada 'Nombre del producto', encuentra el 'Modelo' de costos cuyas
    palabras esten TODAS contenidas en el nombre (y el mas especifico si hay
    mas de un candidato, ej. 'Imperial Con cierre' antes que 'Imperial')."""
    modelos_tokens = {m: (set(_norm_modelo(m).split()) - STOP_WORDS_MODELO) for m in costos['Modelo']}

    def mejor_match(nombre):
        if pd.isna(nombre):
            return None
        tokens_prod = set(_norm_modelo(nombre).split())
        candidatos = [(len(tk), m) for m, tk in modelos_tokens.items() if tk and tk.issubset(tokens_prod)]
        if not candidatos:
            return None
        candidatos.sort(reverse=True)
        return candidatos[0][1]

    return df_ventas['Nombre del producto'].apply(mejor_match)


def metricas_margen(df_ventas, paid, costos, dias, offset_dias=0):
    """Margen neto real de los ultimos N dias, usando el costo por modelo y
    diferenciando ganancia por cuotas vs. transferencia (columnas que ya trae
    el archivo de costos)."""
    v = paid.copy()
    v['modelo_asignado'] = asignar_modelos(v, costos)
    v = v.merge(
        costos[['Modelo', 'Ganancia Neta en 9 pagos', 'Ganancia neta pagando por tranfer']],
        left_on='modelo_asignado', right_on='Modelo', how='left'
    )
    v['es_cuotas'] = v['cuotas_num'].fillna(0) >= 2
    v['ganancia_unit'] = np.where(v['es_cuotas'], v['Ganancia Neta en 9 pagos'], v['Ganancia neta pagando por tranfer'])
    v['ingreso_item'] = v['Cantidad del producto'] * v['Precio del producto']
    v['ganancia_item'] = v['ganancia_unit'] * v['Cantidad del producto']

    max_fecha = v['fecha_dt'].dt.normalize().max() - pd.Timedelta(days=offset_dias)
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)
    ventana = v[(v['fecha_dt'].dt.normalize() >= min_fecha) & (v['fecha_dt'].dt.normalize() <= max_fecha)]

    con_costo = ventana[ventana['ganancia_unit'].notna()]
    sin_costo = ventana[ventana['ganancia_unit'].isna()]

    ingresos_totales = ventana['ingreso_item'].sum()
    ingresos_con_costo = con_costo['ingreso_item'].sum()
    ganancia = con_costo['ganancia_item'].sum()

    sin_costo_top = (
        sin_costo.groupby('Nombre del producto')['ingreso_item'].sum()
        .sort_values(ascending=False).head(10).reset_index().to_dict('records')
    )

    return {
        'cobertura_pct': round(100 * ingresos_con_costo / ingresos_totales, 1) if ingresos_totales else 0,
        'ingresos_con_costo': round(ingresos_con_costo),
        'ganancia_neta': round(ganancia),
        'margen_pct': round(100 * ganancia / ingresos_con_costo, 1) if ingresos_con_costo else 0,
        'productos_sin_costo': sin_costo_top,
    }


def forecast_reposicion(df_ventas, paid, df_prod, costos, dias, df_ml=None):
    """Demanda combinada (Tiendanube + Mercado Libre, si esta disponible) por
    Modelo en los ultimos N dias, cruzada contra el stock actual (Tiendanube).
    Devuelve el ranking con nivel de alerta para saber a que modelo priorizar
    la reposicion."""
    max_fecha = paid['fecha_dt'].dt.normalize().max()
    min_fecha = max_fecha - pd.Timedelta(days=dias - 1)

    # demanda en Tiendanube, por modelo
    v_tn = paid[(paid['fecha_dt'].dt.normalize() >= min_fecha) & (paid['fecha_dt'].dt.normalize() <= max_fecha)].copy()
    v_tn['modelo_asignado'] = asignar_modelos(v_tn, costos)
    demanda_tn = v_tn.groupby('modelo_asignado')['Cantidad del producto'].sum()

    # demanda en Mercado Libre, por modelo (si hay archivo)
    demanda_ml = pd.Series(dtype=float)
    cobertura_ml = None
    if df_ml is not None:
        v_ml = df_ml[
            (df_ml['fecha_dt'].dt.normalize() >= min_fecha) & (df_ml['fecha_dt'].dt.normalize() <= max_fecha)
        ].copy()
        v_ml_renombrado = v_ml.rename(columns={'Título de la publicación': 'Nombre del producto'})
        v_ml['modelo_asignado'] = asignar_modelos(v_ml_renombrado, costos)
        cobertura_ml = round(100 * v_ml['modelo_asignado'].notna().sum() / len(v_ml), 1) if len(v_ml) else 0
        demanda_ml = v_ml.groupby('modelo_asignado')['Unidades'].sum()

    demanda_total = demanda_tn.add(demanda_ml, fill_value=0)

    # stock actual (Tiendanube), por modelo
    prod = nombre_fill_productos(df_prod)
    prod_renombrado = prod.rename(columns={'nombre_producto': 'Nombre del producto'})
    prod['modelo_asignado'] = asignar_modelos(prod_renombrado, costos)
    stock_modelo = prod.groupby('modelo_asignado')['stock_total'].sum()

    tabla = pd.DataFrame({'unidades_30d': demanda_total}).join(stock_modelo.rename('stock_actual'), how='outer').fillna(0)
    tabla = tabla[tabla.index.notna()]
    tabla['venta_diaria'] = tabla['unidades_30d'] / dias
    tabla['dias_de_stock'] = np.where(tabla['venta_diaria'] > 0, tabla['stock_actual'] / tabla['venta_diaria'], np.inf)

    def nivel(row):
        if row['venta_diaria'] == 0:
            return '⚪ sin demanda' if row['stock_actual'] > 0 else '—'
        if row['dias_de_stock'] < 7:
            return '🔴 urgente'
        if row['dias_de_stock'] < 15:
            return '🟠 atención'
        return '🟢 ok'

    tabla['alerta'] = tabla.apply(nivel, axis=1)
    tabla = tabla.sort_values('dias_de_stock')
    tabla['dias_de_stock'] = tabla['dias_de_stock'].replace(np.inf, None)

    return {
        'tabla': tabla.reset_index().rename(columns={'index': 'Modelo'}).round(1).to_dict('records'),
        'cobertura_ml_pct': cobertura_ml,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ventas_csv')
    ap.add_argument('productos_csv')
    ap.add_argument('--dias', type=int, default=30)
    args = ap.parse_args()

    df_ventas = cargar_ventas(args.ventas_csv)
    df_prod = cargar_productos(args.productos_csv)
    paid = df_ventas[df_ventas['Estado del pago'] == 'Recibido'].copy()

    resultado = {
        'ventana': metricas_ventana(paid, args.dias),
        'historico': metricas_historicas(paid),
        'riesgo_stock': chequeo_stock(paid, df_prod, args.dias),
        'dias_segunda_compra': dias_hasta_segunda_compra(paid),
        'cancelaciones_medio_pago': cancelaciones_por_medio_pago(df_ventas),
        'cancelaciones_provincia': cancelaciones_por_provincia(df_ventas),
        'stock_nunca_vendido': stock_nunca_vendido(paid, df_prod),
    }

    print(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
