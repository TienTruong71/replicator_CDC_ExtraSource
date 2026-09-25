import time

try:
    from logger import Logger
except ImportError:
    from .logger import Logger


_FK_CACHE = {}
_FK_CACHE_TS = {}
_FK_CACHE_TTL = 300.0


def discover_fk_relationships(dst_conn, tables, cache_key="default"):
    now = time.time()
    if cache_key in _FK_CACHE and now - _FK_CACHE_TS.get(cache_key, 0) < _FK_CACHE_TTL:
        return _FK_CACHE[cache_key]

    tables_lower = {t.lower() for t in tables}
    cursor = dst_conn.cursor()
    cursor.execute("""
        SELECT
            fk.object_id                AS fk_oid,
            fk.name                     AS fk_name,
            cpar.name                   AS parent_table,
            cpar_col.name               AS parent_col,
            cchild.name                 AS child_table,
            cchild_col.name             AS child_col
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables cpar            ON fk.referenced_object_id = cpar.object_id
        JOIN sys.columns cpar_col       ON cpar_col.object_id = cpar.object_id
                                       AND cpar_col.column_id = fkc.referenced_column_id
        JOIN sys.tables cchild          ON fk.parent_object_id = cchild.object_id
        JOIN sys.columns cchild_col     ON cchild_col.object_id = cchild.object_id
                                       AND cchild_col.column_id = fkc.parent_column_id
        WHERE SCHEMA_NAME(cpar.schema_id) = 'dbo'
          AND SCHEMA_NAME(cchild.schema_id) = 'dbo'
        ORDER BY fk.object_id, fkc.constraint_column_id
    """)
    rows = cursor.fetchall()
    cursor.close()

    by_fk = {}
    for fk_oid, fk_name, parent_table, parent_col, child_table, child_col in rows:
        by_fk.setdefault(fk_oid, {"name": fk_name, "cols": []})
        by_fk[fk_oid]["cols"].append((parent_table, parent_col, child_table, child_col))

    result = {}
    for fk_oid, info in by_fk.items():
        cols = info["cols"]
        if len(cols) > 1:
            Logger.warn(
                f"Skipping composite FK '{info['name']}' ({len(cols)} columns) "
                f"— FK remap supports single-column FKs only."
            )
            continue
        parent_table, parent_col, child_table, child_col = cols[0]
        if child_table.lower() not in tables_lower or parent_table.lower() not in tables_lower:
            continue
        result.setdefault(child_table.lower(), []).append((child_col, parent_table, parent_col))

    _FK_CACHE[cache_key] = result
    _FK_CACHE_TS[cache_key] = now
    link_count = sum(len(v) for v in result.values())
    if link_count:
        Logger.info(f"Discovered {link_count} FK link(s) across {len(result)} child table(s) for remap.")
    return result


def topological_order(tables, fk_map):
    lower_to_orig = {}
    for t in tables:
        lower_to_orig.setdefault(t.lower(), t)
    present = list(lower_to_orig.keys())
    present_set = set(present)

    deps = {t: set() for t in present}
    for child_l, links in fk_map.items():
        if child_l not in present_set:
            continue
        for _fk_col, parent_table, _parent_pk in links:
            p_l = parent_table.lower()
            if p_l in present_set and p_l != child_l:
                deps[child_l].add(p_l)

    ordered = []
    state = {}

    def visit(node):
        s = state.get(node)
        if s == 1:
            return
        if s == 0:
            Logger.warn(f"FK cycle detected involving '{node}'; using input order for it.")
            return
        state[node] = 0
        for dep in deps.get(node, ()):
            visit(dep)
        state[node] = 1
        ordered.append(node)

    for t in present:
        visit(t)

    return [lower_to_orig[t] for t in ordered]


def build_parent_id_map(dst_conn, parent_table, parent_pk_col, source_id, needed_src_ids):
    if not needed_src_ids:
        return {}
    table_clean = parent_table.replace('[', '').replace(']', '').replace('dbo.', '')
    ids = [str(x) for x in needed_src_ids if x is not None]
    id_map = {}
    cursor = dst_conn.cursor()
    try:
        chunk = 1000
        for i in range(0, len(ids), chunk):
            part = ids[i:i + chunk]
            placeholders = ", ".join("?" for _ in part)
            cursor.execute(
                f"SELECT [source_record_id], [{parent_pk_col}] FROM dbo.[{table_clean}] "
                f"WHERE [sync_source_id] = ? AND [source_record_id] IN ({placeholders})",
                (source_id, *part),
            )
            for src_rec, new_pk in cursor.fetchall():
                if src_rec is not None:
                    id_map[str(src_rec)] = new_pk
    finally:
        cursor.close()
    return id_map


def remap_child_fks(rows, links, id_maps):
    ready, deferred = [], []
    for row in rows:
        lower_index = {k.lower(): k for k in row.keys()}
        defer = False
        for fk_col, parent_table, _parent_pk in links:
            key = lower_index.get(fk_col.lower())
            if key is None:
                continue
            val = row.get(key)
            if val is None:
                continue
            new_pk = id_maps.get(parent_table.lower(), {}).get(str(val))
            if new_pk is None:
                defer = True
                break
            row[key] = new_pk
        (deferred if defer else ready).append(row)
    return ready, deferred
