"""Bulk-seed the quota_items table via programmatic combinations.

Generates realistic construction quota entries by crossing:
- 分部 (chapter) × 规格/等级 × 构件/部位

Target: ~1000-1500 entries covering major chapters.

Codes follow the pattern D-<ChapterLetter><SectionNN><SeqNN>:
  Example: D-D010107 = 混凝土/基础/C30

Run:
    python seed_quota_bulk.py           # clears + bulk-seeds (merges with hand data)
    python seed_quota_bulk.py --append  # keep existing, only add new
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from app.db.session import SessionLocal
from app.models.boq_item import BoqItem
from app.models.calc_result import CalcResult
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.quota_item import QuotaItem

# ── Shared dimension dictionaries ───────────────────────────────

CONCRETE_GRADES = ["C15", "C20", "C25", "C30", "C35", "C40", "C45", "C50"]

# 人工含量基数 (labor coefficient)；按等级略微增加因振捣/养护要求
# 材料含量基数 (material coefficient)；按等级线性递增
# 机械含量基数 (machine coefficient)
CONCRETE_MEMBERS = [
    # (key, name, unit, labor_base, mat_base, mach_base)
    ("cushion", "混凝土垫层", "m³", 2.0, 4.3, 0.8),
    ("strip_foundation", "条形基础混凝土", "m³", 2.8, 5.2, 1.3),
    ("iso_foundation", "独立基础混凝土", "m³", 3.0, 5.3, 1.4),
    ("raft_foundation", "筏板基础混凝土", "m³", 3.2, 5.6, 1.6),
    ("pile_cap", "承台混凝土", "m³", 3.3, 5.5, 1.6),
    ("column_frame", "框架柱混凝土", "m³", 3.5, 5.4, 1.5),
    ("column_constructional", "构造柱混凝土", "m³", 4.8, 5.8, 1.0),
    ("shear_wall", "剪力墙混凝土", "m³", 3.2, 5.6, 1.4),
    ("retaining_wall", "挡土墙混凝土", "m³", 2.8, 5.3, 1.4),
    ("beam_frame", "框架梁混凝土", "m³", 3.6, 5.5, 1.5),
    ("beam_ring", "圈梁混凝土", "m³", 4.2, 5.8, 1.1),
    ("beam_lintel", "过梁混凝土", "m³", 4.1, 5.6, 1.0),
    ("slab_cast", "现浇楼板混凝土", "m³", 3.1, 5.5, 1.2),
    ("slab_roof", "屋面板混凝土", "m³", 3.3, 5.6, 1.3),
    ("stair", "楼梯混凝土", "m³", 4.2, 5.6, 1.2),
    ("parapet", "女儿墙混凝土", "m³", 4.5, 5.5, 1.0),
    ("coping", "压顶混凝土", "m³", 4.3, 5.4, 0.9),
    ("equipment_base", "设备基础混凝土", "m³", 4.5, 5.8, 1.5),
]

REBAR_SPECS = [
    # (key, name, labor_hrs, material_coef, machine_coef)
    ("hpb300_d6", "HPB300 φ6", 12.0, 1.06, 0.5),
    ("hpb300_d8", "HPB300 φ8", 11.0, 1.05, 0.5),
    ("hpb300_d10", "HPB300 φ10", 10.5, 1.05, 0.6),
    ("hrb400_d8", "HRB400 φ8", 12.5, 1.05, 0.6),
    ("hrb400_d10", "HRB400 φ10", 11.5, 1.05, 0.7),
    ("hrb400_d12", "HRB400 φ12", 10.8, 1.05, 0.7),
    ("hrb400_d14", "HRB400 φ14", 10.2, 1.05, 0.8),
    ("hrb400_d16", "HRB400 φ16", 9.8, 1.04, 0.8),
    ("hrb400_d18", "HRB400 φ18", 9.5, 1.04, 0.8),
    ("hrb400_d20", "HRB400 φ20", 9.0, 1.04, 0.9),
    ("hrb400_d22", "HRB400 φ22", 8.8, 1.04, 0.9),
    ("hrb400_d25", "HRB400 φ25", 8.5, 1.03, 1.0),
    ("hrb400_d28", "HRB400 φ28", 8.2, 1.03, 1.0),
    ("hrb400_d32", "HRB400 φ32", 8.0, 1.03, 1.1),
    ("hrb500_d16", "HRB500 φ16", 10.0, 1.04, 0.9),
    ("hrb500_d20", "HRB500 φ20", 9.5, 1.04, 1.0),
    ("hrb500_d25", "HRB500 φ25", 9.0, 1.03, 1.1),
]

REBAR_MEMBERS = [
    ("basic", "基础钢筋"),
    ("column", "柱钢筋"),
    ("beam", "梁钢筋"),
    ("slab", "板钢筋"),
    ("wall", "墙钢筋"),
    ("stair", "楼梯钢筋"),
    ("cap", "承台钢筋"),
]

FORMWORK_MEMBERS = [
    # (key, name, unit, labor, mat, mach)
    ("foundation", "基础模板", "m²", 1.2, 0.7, 0.2),
    ("strip_foundation", "条基模板", "m²", 1.1, 0.7, 0.2),
    ("raft_foundation", "筏板模板", "m²", 1.0, 0.6, 0.2),
    ("pile_cap", "承台模板", "m²", 1.3, 0.7, 0.2),
    ("column", "柱模板", "m²", 2.0, 0.9, 0.3),
    ("wall", "墙模板", "m²", 1.8, 0.9, 0.3),
    ("beam", "梁模板", "m²", 1.9, 0.8, 0.3),
    ("slab", "板模板", "m²", 1.5, 0.7, 0.2),
    ("stair", "楼梯模板", "m²", 2.5, 1.0, 0.3),
    ("parapet", "女儿墙模板", "m²", 1.6, 0.8, 0.2),
    ("lintel", "过梁模板", "m²", 1.7, 0.7, 0.2),
]
FORMWORK_TYPES = [
    # (key, suffix, mat_mul, labor_mul)
    ("wood", "木模板", 1.0, 1.0),
    ("steel", "钢模板", 1.4, 0.9),
    ("plywood", "胶合板模板", 1.2, 0.95),
    ("aluminum", "铝模板", 2.2, 0.75),
]

MASONRY_TYPES = [
    # (key, name, unit, labor_base, mat_base, mach_base)
    ("solid_brick", "实心砖砌体", "m³", 5.0, 3.5, 0.2),
    ("porous_brick", "多孔砖砌体", "m³", 4.5, 3.3, 0.2),
    ("hollow_brick", "空心砖砌体", "m³", 4.0, 3.0, 0.2),
    ("aac_block", "加气混凝土砌块", "m³", 3.2, 3.8, 0.3),
    ("ceramsite_block", "陶粒空心砌块", "m³", 3.5, 3.5, 0.3),
    ("concrete_block", "混凝土砌块", "m³", 3.8, 3.6, 0.2),
    ("lightweight_block", "轻集料砌块", "m³", 3.3, 3.7, 0.3),
]
MASONRY_THICKNESSES = [
    # (key, name, adj_factor) — 厚度影响人工/材料小幅
    ("t100", "100mm", 0.90),
    ("t120", "120mm", 0.95),
    ("t180", "180mm", 1.00),
    ("t200", "200mm", 1.00),
    ("t240", "240mm", 1.05),
    ("t370", "370mm", 1.10),
]
MASONRY_MORTAR_TYPES = [
    ("cement", "水泥砂浆", 1.0),
    ("mixed", "混合砂浆", 0.95),
]

PLASTER_PARTS = [
    # (key, name, unit, labor, mat, mach)
    ("inner_wall", "内墙抹灰", "m²", 1.2, 0.6, 0.0),
    ("outer_wall", "外墙抹灰", "m²", 1.5, 0.8, 0.1),
    ("ceiling", "天棚抹灰", "m²", 1.3, 0.6, 0.0),
    ("column", "独立柱抹灰", "m²", 1.6, 0.7, 0.0),
    ("beam", "梁侧抹灰", "m²", 1.5, 0.7, 0.0),
    ("stair_soffit", "楼梯底抹灰", "m²", 1.8, 0.7, 0.0),
    ("parapet", "女儿墙抹灰", "m²", 1.4, 0.7, 0.0),
]
PLASTER_MORTARS = [
    # (key, suffix, mat_mul)
    ("cement", "水泥砂浆", 1.0),
    ("mixed", "混合砂浆", 1.05),
    ("gypsum", "石膏砂浆", 1.2),
    ("thermal", "保温砂浆", 1.4),
    ("polymer", "聚合物砂浆", 1.3),
]

FLOOR_TYPES = [
    # (key, name, unit, labor, mat, mach)
    ("cement_mortar", "水泥砂浆楼地面", "m²", 0.8, 0.5, 0.0),
    ("fine_concrete", "细石混凝土地面", "m²", 1.0, 1.0, 0.2),
    ("epoxy", "环氧地坪漆", "m²", 0.5, 1.5, 0.0),
    ("self_leveling", "自流平地面", "m²", 0.6, 2.0, 0.0),
    ("ceramic_tile_300", "地砖 300×300", "m²", 1.0, 1.5, 0.0),
    ("ceramic_tile_600", "地砖 600×600", "m²", 1.1, 1.8, 0.0),
    ("ceramic_tile_800", "地砖 800×800", "m²", 1.2, 2.2, 0.0),
    ("antiskid_tile", "防滑地砖", "m²", 1.0, 1.8, 0.0),
    ("marble", "大理石地面", "m²", 1.5, 5.0, 0.0),
    ("granite", "花岗岩地面", "m²", 1.5, 4.5, 0.0),
    ("terrazzo", "水磨石地面", "m²", 1.8, 2.0, 0.1),
    ("wood_floor_solid", "实木地板", "m²", 0.9, 4.5, 0.0),
    ("wood_floor_laminate", "强化复合地板", "m²", 0.7, 2.0, 0.0),
    ("pvc_roll", "PVC卷材地板", "m²", 0.5, 1.8, 0.0),
    ("rubber_floor", "橡胶地板", "m²", 0.6, 2.5, 0.0),
    ("carpet_roll", "地毯（卷材）", "m²", 0.4, 1.5, 0.0),
    ("carpet_block", "方块地毯", "m²", 0.5, 2.0, 0.0),
    ("raised_floor", "防静电架空地板", "m²", 0.8, 3.0, 0.0),
    ("blind_track", "盲道砖", "m²", 0.9, 1.5, 0.0),
    ("stone_mosaic", "石材拼花地面", "m²", 2.5, 8.0, 0.0),
    ("outdoor_deck", "户外防腐木地板", "m²", 1.0, 3.5, 0.0),
    ("concrete_polished", "混凝土抐光地面", "m²", 1.2, 1.0, 0.3),
    ("resin_floor", "树脂地坡", "m²", 0.6, 2.8, 0.0),
    ("sports_floor", "运动地板（PVC）", "m²", 0.7, 3.5, 0.0),
]

WALL_FINISH_TYPES = [
    ("emulsion_paint", "乳胶漆饰面", "m²", 0.5, 0.4, 0.0),
    ("latex_paint", "内墙涂料", "m²", 0.5, 0.4, 0.0),
    ("exterior_paint", "外墙涂料", "m²", 0.6, 0.6, 0.1),
    ("texture_paint", "真石漆", "m²", 0.8, 1.5, 0.1),
    ("exterior_tile", "外墙面砖", "m²", 1.5, 2.5, 0.1),
    ("interior_tile_300", "内墙砖 300×600", "m²", 1.2, 1.5, 0.0),
    ("interior_tile_600", "内墙砖 600×600", "m²", 1.3, 1.8, 0.0),
    ("stone_cladding", "外墙石材干挂", "m²", 2.2, 6.0, 0.2),
    ("stone_veneer", "外墙石材湿贴", "m²", 1.8, 5.0, 0.1),
    ("wallpaper", "墙纸铺贴", "m²", 0.5, 1.2, 0.0),
    ("wood_veneer", "木饰面墙板", "m²", 1.2, 3.5, 0.0),
    ("soft_package", "软包墙面", "m²", 1.5, 4.0, 0.0),
    ("putty_scraping", "墙面刮腻子", "m²", 0.4, 0.3, 0.0),
    ("base_coat", "墙面基层处理", "m²", 0.3, 0.2, 0.0),
    ("grc_panel", "GRC装饰板", "m²", 1.5, 5.0, 0.2),
    ("glass_mosaic", "玻璃马赛克", "m²", 1.8, 4.0, 0.0),
    ("silicone_paint", "硬氨油漆", "m²", 0.3, 0.8, 0.0),
    ("aluminum_panel", "铝单板幕墙饰面", "m²", 2.0, 6.0, 0.2),
    ("ceramic_panel", "陶板幕墙饰面", "m²", 2.2, 7.0, 0.2),
    ("fiber_cement_board", "纤维水泥板墙面", "m²", 1.0, 2.5, 0.1),
]

CEILING_TYPES = [
    ("gypsum_flat", "石膏板平顶", "m²", 1.2, 1.5, 0.0),
    ("gypsum_level", "石膏板叠级吊顶", "m²", 1.8, 2.2, 0.0),
    ("gypsum_curve", "石膏板造型吊顶", "m²", 2.2, 2.8, 0.0),
    ("mineral_wool", "矿棉板吊顶", "m²", 0.8, 1.4, 0.0),
    ("aluminum_square", "铝扣板吊顶 600×600", "m²", 0.8, 2.0, 0.0),
    ("aluminum_strip", "铝条形板吊顶", "m²", 0.9, 2.2, 0.0),
    ("grille", "格栅吊顶", "m²", 1.0, 2.5, 0.0),
    ("pvc", "PVC扣板吊顶", "m²", 0.6, 1.2, 0.0),
    ("cement_board", "水泥纤维板吊顶", "m²", 1.0, 1.8, 0.0),
    ("light_steel_keel", "轻钢龙骨验架", "m²", 1.0, 1.2, 0.0),
    ("wood_veneer_ceiling", "木饰面吹顶", "m²", 1.5, 3.5, 0.0),
    ("metal_strip_ceiling", "金属条板吹顶", "m²", 1.0, 2.8, 0.0),
    ("stretch_ceiling", "软膜天花", "m²", 0.8, 3.0, 0.0),
    ("exposed_ceiling", "裸顶处理（喷漆）", "m²", 0.5, 0.6, 0.1),
    ("acoustic_panel", "吸音板吹顶", "m²", 1.2, 2.5, 0.0),
    ("bamboo_ceiling", "竹吊顶", "m²", 1.0, 2.0, 0.0),
    ("wooden_grille", "木格栅吊顶", "m²", 1.2, 2.5, 0.0),
    ("plastic_grille", "塑料格栅吊顶", "m²", 0.9, 1.8, 0.0),
]

DOOR_WINDOW_TYPES = [
    ("wood_door", "木门安装", "樘", 2.0, 5.0, 0.0),
    ("flush_door", "夹板门安装", "樘", 1.8, 4.5, 0.0),
    ("steel_door", "钢质门安装", "樘", 2.2, 7.0, 0.1),
    ("fire_door_a", "甲级防火门", "樘", 2.5, 10.0, 0.1),
    ("fire_door_b", "乙级防火门", "樘", 2.5, 8.5, 0.1),
    ("fire_door_c", "丙级防火门", "樘", 2.3, 7.0, 0.1),
    ("security_door", "防盗门", "樘", 2.0, 6.0, 0.0),
    ("glass_door", "玻璃门", "m²", 2.0, 8.0, 0.2),
    ("rolling_shutter", "卷帘门", "m²", 1.5, 4.0, 0.2),
    ("auto_door", "自动感应门", "樘", 3.0, 15.0, 0.3),
    ("alum_window_sliding", "铝合金推拉窗", "m²", 1.3, 3.5, 0.1),
    ("alum_window_casement", "铝合金平开窗", "m²", 1.5, 4.0, 0.1),
    ("alum_window_fixed", "铝合金固定窗", "m²", 1.2, 3.3, 0.1),
    ("broken_bridge_window", "断桥铝合金窗", "m²", 1.6, 5.0, 0.1),
    ("plastic_window", "塑钢窗", "m²", 1.4, 3.0, 0.1),
    ("louver", "铝合金百叶窗", "m²", 1.0, 2.0, 0.0),
    ("curtain_wall_glass", "玻璃幕墙", "m²", 3.0, 8.0, 0.5),
    ("curtain_wall_stone", "石材幕墙", "m²", 2.8, 10.0, 0.5),
    ("curtain_wall_metal", "铝板幕墙", "m²", 2.5, 7.5, 0.5),
    ("garage_door", "车库门", "m²", 1.2, 3.5, 0.2),
    ("folding_door", "折叠门", "m²", 1.5, 4.0, 0.1),
    ("sliding_door", "推拉门", "m²", 1.3, 3.8, 0.1),
    ("soundproof_door", "隔声门", "樘", 3.0, 12.0, 0.1),
    ("cleanroom_door", "洁净门", "樘", 2.8, 10.0, 0.1),
    ("skylight", "天窗", "m²", 2.0, 5.0, 0.2),
    ("shutter_window", "百叶窗（防雨）", "m²", 1.2, 2.5, 0.1),
    ("curtain_wall_point", "点式玻璃幕墙", "m²", 3.2, 9.0, 0.5),
]

WATERPROOF_MATERIALS = [
    # (key, name, labor, mat, mach)
    ("sbs", "SBS改性沥青防水卷材", 1.0, 2.5, 0.1),
    ("app", "APP改性沥青防水卷材", 1.0, 2.6, 0.1),
    ("polyurethane", "聚氨酯防水涂料", 0.8, 1.8, 0.0),
    ("acrylic", "丙烯酸防水涂料", 0.7, 1.6, 0.0),
    ("cement_based", "水泥基渗透结晶防水", 0.9, 1.5, 0.0),
    ("self_adhesive", "自粘防水卷材", 0.9, 2.3, 0.0),
    ("pvc_membrane", "PVC防水卷材", 1.0, 2.8, 0.1),
    ("tpo_membrane", "TPO防水卷材", 1.1, 3.0, 0.1),
]
WATERPROOF_PARTS = [
    ("roof", "屋面防水"),
    ("bathroom", "卫生间防水"),
    ("basement_floor", "地下室底板防水"),
    ("basement_wall", "地下室外墙防水"),
    ("balcony", "阳台防水"),
    ("kitchen", "厨房防水"),
    ("outer_wall", "外墙防水"),
]
WATERPROOF_LAYERS = [
    ("single", "单层", 1.0),
    ("double", "双层", 1.85),
]

INSULATION_TYPES = [
    ("rock_wool", "岩棉保温板", 0.6, 1.5, 0.1),
    ("xps", "挤塑聚苯板 XPS", 0.5, 1.2, 0.0),
    ("eps", "模塑聚苯板 EPS", 0.5, 1.0, 0.0),
    ("phenolic", "酚醛泡沫保温板", 0.6, 1.8, 0.0),
    ("pu_spray", "聚氨酯喷涂保温", 0.7, 2.0, 0.1),
    ("glass_wool", "玻璃棉保温", 0.5, 1.3, 0.0),
    ("aac_block_ins", "加气块保温", 0.8, 1.8, 0.1),
]
INSULATION_PARTS = [
    ("outer_wall", "外墙保温"),
    ("roof", "屋面保温"),
    ("floor", "楼地面保温"),
    ("ceiling", "顶棚保温"),
    ("basement", "地下室保温"),
]
INSULATION_THICKNESSES = [
    ("t30", "30mm", 0.85),
    ("t50", "50mm", 1.0),
    ("t80", "80mm", 1.2),
    ("t100", "100mm", 1.4),
]

EARTHWORK_ITEMS = [
    ("manual_excav", "人工挖土方", "m³", 3.0, 0.0, 0.0),
    ("machine_excav_i_ii", "机械挖土方 Ⅰ-Ⅱ类土", "m³", 0.4, 0.0, 3.0),
    ("machine_excav_iii", "机械挖土方 Ⅲ类土", "m³", 0.5, 0.0, 3.5),
    ("machine_excav_iv", "机械挖土方 Ⅳ类土", "m³", 0.6, 0.0, 4.2),
    ("manual_backfill", "人工回填土方", "m³", 1.0, 0.5, 0.5),
    ("machine_backfill", "机械回填土方", "m³", 0.3, 0.3, 2.0),
    ("compacted_backfill", "分层夯实回填", "m³", 0.5, 0.4, 1.2),
    ("soil_transport_1km", "余土外运 1km", "m³", 0.1, 0.0, 2.5),
    ("soil_transport_5km", "余土外运 5km", "m³", 0.1, 0.0, 3.5),
    ("soil_transport_10km", "余土外运 10km", "m³", 0.1, 0.0, 5.0),
    ("rock_blasting", "石方爆破开挖", "m³", 1.0, 3.0, 8.0),
    ("rock_hammer", "石方机械开挖", "m³", 0.8, 0.5, 6.5),
    ("support_steel_sheet", "钢板桩支护", "m²", 1.5, 4.0, 3.0),
    ("support_soil_nail", "土钉墙支护", "m²", 2.0, 3.5, 1.5),
    ("support_pile_wall", "排桩支护", "m", 2.5, 5.0, 4.0),
    ("well_point", "轻型井点降水", "m", 0.5, 0.2, 1.5),
    ("deep_well", "管井降水", "口", 5.0, 8.0, 3.0),
    ("manual_trench", "人工挖沟槽", "m³", 3.5, 0.0, 0.0),
    ("machine_trench", "机械挖沟槽", "m³", 0.5, 0.0, 3.2),
    ("manual_pit", "人工挖基坑", "m³", 3.2, 0.0, 0.0),
    ("machine_pit", "机械挖基坑", "m³", 0.5, 0.0, 3.3),
    ("sand_backfill", "砂石回填", "m³", 0.8, 1.5, 0.8),
    ("lime_soil_backfill", "灰土回填", "m³", 0.6, 0.8, 0.5),
    ("grouting", "注浆加固", "m³", 1.5, 5.0, 2.0),
    ("geotextile", "土工布铺设", "m²", 0.2, 0.5, 0.0),
    ("geonet", "土工格栅铺设", "m²", 0.25, 0.8, 0.0),
    ("slope_shotcrete", "喷射混凝土护面", "m²", 1.5, 2.5, 1.0),
    ("dewatering_trench", "排水明沟", "m", 0.8, 0.5, 0.3),
    ("foundation_leveling", "场地平整", "m²", 0.1, 0.0, 0.3),
    ("trial_pit", "试坑", "m³", 4.0, 0.0, 0.0),
    ("excavation_4_6m", "机械挖土 4-6m深", "m³", 0.6, 0.0, 4.0),
    ("excavation_gt6m", "机械挖土 >6m深", "m³", 0.8, 0.0, 5.2),
]

PILE_ITEMS = [
    ("precast_400", "预制桩 □400 打桩", "m", 1.0, 5.0, 5.0),
    ("precast_500", "预制桩 □500 打桩", "m", 1.1, 6.0, 5.5),
    ("static_pile_400", "静压预制桩 □400", "m", 0.9, 5.0, 4.8),
    ("static_pile_500", "静压预制桩 □500", "m", 1.0, 6.0, 5.3),
    ("cast_in_place_600", "钻孔灌注桩 φ600", "m", 1.8, 3.5, 5.5),
    ("cast_in_place_800", "钻孔灌注桩 φ800", "m", 2.0, 4.5, 6.0),
    ("cast_in_place_1000", "钻孔灌注桩 φ1000", "m", 2.2, 6.0, 6.5),
    ("cast_in_place_1200", "钻孔灌注桩 φ1200", "m", 2.5, 8.5, 7.0),
    ("cfg_400", "CFG桩 φ400", "m", 1.0, 3.0, 4.0),
    ("cfg_500", "CFG桩 φ500", "m", 1.1, 3.8, 4.3),
    ("mixing_pile_500", "水泥土搅拌桩 φ500", "m", 0.8, 2.5, 3.5),
    ("mixing_pile_600", "水泥土搅拌桩 φ600", "m", 0.9, 3.0, 3.8),
    ("manual_excav_pile", "人工挖孔桩", "m³", 8.0, 3.0, 0.5),
    ("anchor_pile", "锚杆", "m", 1.5, 3.0, 2.0),
    ("pile_test_static", "桩静载试验", "根", 2.0, 5.0, 3.0),
    ("pile_test_dynamic", "桩低应变检测", "根", 0.5, 0.5, 0.0),
    ("pile_cutoff", "桩头破除", "根", 2.0, 0.2, 0.5),
    ("cast_in_place_1500", "钻孔灌注桩 φ1500", "m", 2.8, 10.0, 7.5),
    ("cast_in_place_1800", "钻孔灌注桩 φ1800", "m", 3.2, 13.0, 8.5),
    ("precast_phc_400", "PHC管桩 φ400 打桩", "m", 0.8, 4.5, 5.0),
    ("precast_phc_500", "PHC管桩 φ500 打桩", "m", 0.9, 5.5, 5.5),
    ("precast_phc_600", "PHC管桩 φ600 打桩", "m", 1.0, 7.0, 6.0),
    ("micropile_150", "微型桩 φ150", "m", 1.2, 2.0, 2.5),
    ("micropile_200", "微型桩 φ200", "m", 1.3, 2.5, 3.0),
    ("jet_grouting_600", "高压旋喷桩 φ600", "m", 1.0, 3.5, 4.0),
]

# 给排水
PLUMBING_PIPES = [
    # (type_key, type_name, labor_base, mat_base, mach_base)
    ("ppr", "PPR给水管", 0.8, 0.6, 0.0),
    ("pe", "PE给水管", 0.7, 0.7, 0.0),
    ("galvanized", "镀锌钢管给水管", 1.0, 1.0, 0.1),
    ("stainless", "不锈钢给水管", 1.2, 2.0, 0.1),
    ("pvc_drain", "PVC排水管", 0.6, 0.5, 0.0),
    ("hdpe_drain", "HDPE排水管", 0.7, 0.8, 0.0),
    ("cast_iron_drain", "柔性铸铁排水管", 1.2, 1.5, 0.1),
]
PLUMBING_SIZES = [
    # (key, spec, size_factor)
    ("dn15", "DN15", 0.8),
    ("dn20", "DN20", 0.85),
    ("dn25", "DN25", 0.9),
    ("dn32", "DN32", 1.0),
    ("dn40", "DN40", 1.1),
    ("dn50", "DN50", 1.2),
    ("dn65", "DN65", 1.35),
    ("dn80", "DN80", 1.5),
    ("dn100", "DN100", 1.7),
    ("dn150", "DN150", 2.0),
    ("dn200", "DN200", 2.4),
]
PLUMBING_METHODS = [
    ("concealed", "暗装", 1.2),
    ("exposed", "明装", 1.0),
]

PLUMBING_FIXTURES = [
    ("valve_gate_dn15", "闸阀 DN15", "个", 0.3, 1.2, 0.0),
    ("valve_gate_dn25", "闸阀 DN25", "个", 0.4, 2.0, 0.0),
    ("valve_gate_dn50", "闸阀 DN50", "个", 0.5, 3.5, 0.0),
    ("valve_ball_dn15", "球阀 DN15", "个", 0.2, 1.0, 0.0),
    ("valve_ball_dn25", "球阀 DN25", "个", 0.3, 1.8, 0.0),
    ("check_valve_dn50", "止回阀 DN50", "个", 0.5, 3.0, 0.0),
    ("water_meter_dn20", "水表 DN20", "个", 0.3, 1.0, 0.0),
    ("water_meter_dn50", "水表 DN50", "个", 0.6, 3.5, 0.0),
    ("floor_drain", "地漏", "个", 0.3, 0.2, 0.0),
    ("toilet", "坐便器安装", "套", 1.5, 3.0, 0.0),
    ("squat_toilet", "蹲便器安装", "套", 1.3, 2.0, 0.0),
    ("basin", "洗脸盆安装", "套", 1.0, 2.0, 0.0),
    ("urinal", "小便器安装", "套", 1.2, 2.2, 0.0),
    ("bathtub", "浴缸安装", "套", 2.5, 5.0, 0.0),
    ("shower", "淋浴器安装", "套", 1.2, 2.5, 0.0),
    ("kitchen_sink", "厨房洗涤盆", "套", 1.0, 2.3, 0.0),
    ("hot_water_tank", "热水器安装", "台", 2.0, 0.0, 0.0),
    ("fire_hose_cabinet", "消火栓箱", "套", 1.5, 3.0, 0.0),
    ("septic_tank", "化粪池", "座", 5.0, 10.0, 2.0),
    ("grease_trap", "隔油池", "座", 4.0, 8.0, 1.5),
    ("water_pump_small", "小型水泵安装", "台", 2.5, 0.0, 0.3),
    ("water_pump_large", "大型水泵安装", "台", 5.0, 0.0, 1.0),
    ("water_tank_3t", "水箱 3t", "座", 2.5, 6.0, 0.5),
    ("water_tank_10t", "水箱 10t", "座", 4.0, 12.0, 1.0),
    ("backflow_preventer", "倒流防止器", "个", 0.5, 2.0, 0.0),
    ("pressure_tank", "气压罐", "台", 2.0, 5.0, 0.5),
    ("water_softener", "软水器安装", "台", 1.5, 0.0, 0.2),
    ("uv_sterilizer", "紫外线消毒器", "台", 1.0, 0.0, 0.0),
    ("expansion_joint_pipe", "管道伸缩节", "个", 0.3, 1.5, 0.0),
    ("pipe_support_light", "轻型管道支架", "个", 0.2, 0.3, 0.0),
    ("pipe_support_heavy", "重型管道支架", "个", 0.5, 1.0, 0.1),
    ("mop_basin", "拖布池安装", "套", 1.0, 1.5, 0.0),
    ("drinking_fountain", "饮水台安装", "台", 1.2, 0.0, 0.0),
]

# 电气
ELECTRICAL_CONDUITS = [
    ("pvc_15", "PVC管 DN15 暗敷", 0.4, 0.3, 0.0),
    ("pvc_20", "PVC管 DN20 暗敷", 0.45, 0.35, 0.0),
    ("pvc_25", "PVC管 DN25 暗敷", 0.5, 0.4, 0.0),
    ("pvc_32", "PVC管 DN32 暗敷", 0.55, 0.5, 0.0),
    ("sc_15", "焊接钢管 SC15", 0.5, 0.6, 0.0),
    ("sc_20", "焊接钢管 SC20", 0.55, 0.7, 0.0),
    ("sc_25", "焊接钢管 SC25", 0.6, 0.8, 0.0),
    ("sc_32", "焊接钢管 SC32", 0.65, 0.9, 0.0),
    ("kbg_20", "KBG管 DN20", 0.45, 0.55, 0.0),
    ("kbg_25", "KBG管 DN25", 0.5, 0.65, 0.0),
]
ELECTRICAL_CABLES = [
    ("bv_2_5", "BV 2.5mm² 导线", 0.1, 0.3, 0.0),
    ("bv_4", "BV 4mm² 导线", 0.12, 0.5, 0.0),
    ("bv_6", "BV 6mm² 导线", 0.15, 0.8, 0.0),
    ("bv_10", "BV 10mm² 导线", 0.18, 1.3, 0.0),
    ("bvr_2_5", "BVR 2.5mm² 软线", 0.1, 0.35, 0.0),
    ("yjv_4x4", "YJV-4×4mm² 电缆", 0.5, 1.5, 0.1),
    ("yjv_4x10", "YJV-4×10mm² 电缆", 0.6, 3.5, 0.1),
    ("yjv_4x25", "YJV-4×25mm² 电缆", 0.8, 8.0, 0.2),
    ("yjv_4x70", "YJV-4×70mm² 电缆", 1.2, 22.0, 0.3),
    ("yjv_4x120", "YJV-4×120mm² 电缆", 1.5, 38.0, 0.4),
    ("yjv_4x185", "YJV-4×185mm² 电缆", 1.8, 58.0, 0.5),
    ("yjv_4x240", "YJV-4×240mm² 电缆", 2.0, 76.0, 0.5),
    ("nh_yjv_4x25", "NH-YJV 耐火 4×25mm²", 0.85, 10.0, 0.2),
    ("nh_yjv_4x70", "NH-YJV 耐火 4×70mm²", 1.3, 27.0, 0.3),
    ("wdz_yjv_4x16", "WDZ 低烟无卤 4×16mm²", 0.7, 6.5, 0.2),
]

ELECTRICAL_FIXTURES = [
    ("switch_single", "单联开关", "个", 0.3, 0.3, 0.0),
    ("switch_double", "双联开关", "个", 0.35, 0.4, 0.0),
    ("switch_triple", "三联开关", "个", 0.4, 0.5, 0.0),
    ("socket_5hole", "五孔插座", "个", 0.3, 0.4, 0.0),
    ("socket_16a", "16A空调插座", "个", 0.35, 0.6, 0.0),
    ("socket_usb", "USB插座", "个", 0.35, 0.8, 0.0),
    ("ground_socket", "地插座", "个", 0.5, 1.5, 0.0),
    ("ceiling_light", "吸顶灯", "套", 0.8, 2.0, 0.0),
    ("pendant_light", "吊灯", "套", 1.0, 3.5, 0.0),
    ("downlight", "筒灯", "套", 0.5, 0.8, 0.0),
    ("led_panel", "LED面板灯", "套", 0.6, 1.5, 0.0),
    ("led_strip", "LED灯带", "m", 0.2, 0.5, 0.0),
    ("street_light", "路灯", "套", 3.0, 8.0, 0.5),
    ("emergency_light", "应急照明灯", "套", 1.0, 2.5, 0.0),
    ("exit_sign", "疏散指示灯", "套", 0.8, 1.5, 0.0),
    ("distribution_box_small", "照明配电箱（小）", "台", 2.0, 5.0, 0.3),
    ("distribution_box_medium", "动力配电箱（中）", "台", 3.5, 10.0, 0.5),
    ("distribution_box_large", "低压配电柜", "台", 6.0, 35.0, 1.0),
    ("cable_tray_200", "桥架 200mm", "m", 0.5, 1.0, 0.1),
    ("cable_tray_400", "桥架 400mm", "m", 0.7, 1.8, 0.1),
    ("cable_tray_600", "桥架 600mm", "m", 0.9, 2.5, 0.1),
    ("bus_duct_400a", "400A 母线", "m", 1.5, 5.0, 0.3),
    ("bus_duct_800a", "800A 母线", "m", 2.0, 9.0, 0.4),
    ("bus_duct_1600a", "1600A 母线", "m", 2.8, 18.0, 0.6),
    ("grounding_grid", "接地装置", "组", 2.0, 1.5, 0.5),
    ("lightning_rod", "避雷针", "组", 2.5, 3.0, 0.5),
    ("lightning_band", "避雷带", "m", 0.3, 0.8, 0.0),
    ("transformer_630", "630kVA 变压器", "台", 20.0, 0.0, 5.0),
    ("transformer_1000", "1000kVA 变压器", "台", 25.0, 0.0, 6.0),
    ("generator_200", "200kW 发电机", "台", 15.0, 0.0, 3.0),
    ("transformer_1600", "1600kVA 变压器", "台", 30.0, 0.0, 7.0),
    ("generator_500", "500kW 发电机", "台", 20.0, 0.0, 5.0),
    ("ats_switch", "ATS 双电源切换开关", "台", 2.0, 5.0, 0.0),
    ("capacitor_bank", "无功补偿柜", "台", 3.0, 8.0, 0.0),
    ("pdu", "PDU 电源分配单元", "台", 0.5, 2.0, 0.0),
    ("smoke_detector_elec", "电气火灾探测器", "个", 0.4, 1.0, 0.0),
    ("cable_tray_800", "桥架 800mm", "m", 1.1, 3.5, 0.2),
    ("cable_tray_1000", "桥架 1000mm", "m", 1.3, 4.5, 0.2),
    ("bus_duct_2500a", "2500A 母线", "m", 3.5, 28.0, 0.8),
    ("bus_duct_3200a", "3200A 母线", "m", 4.0, 38.0, 1.0),
    ("led_spotlight", "LED射灯", "套", 0.4, 0.6, 0.0),
    ("landscape_light", "景观灯", "套", 2.0, 5.0, 0.3),
    ("dimmer_switch", "调光开关", "个", 0.4, 1.0, 0.0),
    ("motion_sensor", "人体感应开关", "个", 0.4, 0.8, 0.0),
]

HVAC_ITEMS = [
    ("duct_300", "镀锌钢板风管 周长≤1000", "m²", 1.2, 1.8, 0.3),
    ("duct_600", "镀锌钢板风管 周长≤2000", "m²", 1.5, 2.2, 0.3),
    ("duct_1000", "镀锌钢板风管 周长＞2000", "m²", 1.8, 2.8, 0.4),
    ("duct_fire", "不锈钢防火风管", "m²", 2.0, 4.0, 0.4),
    ("duct_flex", "软管", "m", 0.5, 1.0, 0.0),
    ("ac_copper_dn10", "空调铜管 DN10", "m", 0.8, 1.5, 0.1),
    ("ac_copper_dn15", "空调铜管 DN15", "m", 0.9, 1.8, 0.1),
    ("ac_copper_dn20", "空调铜管 DN20", "m", 1.0, 2.5, 0.1),
    ("ac_split", "分体空调安装", "台", 2.5, 0.0, 0.5),
    ("ac_vrv_indoor", "VRV 室内机", "台", 3.0, 0.0, 0.5),
    ("ac_vrv_outdoor", "VRV 室外机", "台", 5.0, 0.0, 2.0),
    ("fan_coil", "风机盘管", "台", 1.5, 0.0, 0.2),
    ("ahu_small", "组合式空调机组（小）", "台", 5.0, 0.0, 1.5),
    ("ahu_large", "组合式空调机组（大）", "台", 8.0, 0.0, 3.0),
    ("cooling_tower", "冷却塔安装", "台", 6.0, 0.0, 2.0),
    ("chiller_water", "水冷冷水机组", "台", 15.0, 0.0, 4.0),
    ("radiator", "散热器安装", "组", 1.0, 3.0, 0.0),
    ("heating_pipe_20", "采暖管道 DN20", "m", 0.8, 1.5, 0.0),
    ("heating_pipe_25", "采暖管道 DN25", "m", 0.9, 1.8, 0.0),
    ("heating_pipe_50", "采暖管道 DN50", "m", 1.2, 3.0, 0.1),
    ("floor_heating", "地板采暖敷设", "m²", 0.5, 2.5, 0.0),
    ("insulation_hvac", "风管保温", "m²", 0.5, 0.8, 0.0),
    ("exhaust_fan_small", "小型排风机", "台", 1.0, 0.0, 0.2),
    ("exhaust_fan_large", "大型排风机", "台", 2.5, 0.0, 0.5),
    ("air_valve", "风量调节阀", "个", 0.5, 1.0, 0.0),
    ("fire_damper", "防火阀", "个", 0.6, 1.8, 0.0),
    ("air_diffuser", "送风口", "个", 0.3, 0.6, 0.0),
    ("return_grille", "回风口", "个", 0.3, 0.5, 0.0),
    ("chiller_air", "风冷冷水机组", "台", 12.0, 0.0, 3.5),
    ("boiler_hot_water", "热水锅炉安装", "台", 20.0, 0.0, 5.0),
    ("expansion_tank", "膊胀水箱", "台", 1.5, 3.0, 0.3),
    ("water_separator", "分集水器安装", "套", 2.0, 5.0, 0.5),
    ("heating_pipe_100", "采暖管道 DN100", "m", 1.5, 4.5, 0.2),
    ("chilled_pipe_dn50", "冷冻水管 DN50", "m", 1.0, 2.5, 0.1),
    ("chilled_pipe_dn80", "冷冻水管 DN80", "m", 1.2, 3.5, 0.1),
    ("chilled_pipe_dn100", "冷冻水管 DN100", "m", 1.5, 4.5, 0.2),
    ("chilled_pipe_dn150", "冷冻水管 DN150", "m", 1.8, 6.0, 0.3),
    ("condensate_dn25", "冷凝水管 DN25", "m", 0.6, 1.0, 0.0),
    ("condensate_dn32", "冷凝水管 DN32", "m", 0.7, 1.2, 0.0),
    ("kitchen_hood", "厨房排油烟罩", "m²", 1.5, 3.0, 0.3),
    ("fresh_air_unit", "新风机组安装", "台", 3.0, 0.0, 0.8),
    ("energy_recovery", "全热交换器", "台", 2.5, 0.0, 0.5),
    ("thermostat", "温控器安装", "个", 0.3, 0.5, 0.0),
    ("balance_valve", "平衡阀安装", "个", 0.5, 2.0, 0.0),
    ("pressure_gauge_hvac", "压力表安装", "个", 0.2, 0.3, 0.0),
    ("thermometer_hvac", "温度计安装", "个", 0.2, 0.3, 0.0),
    ("duct_silencer", "风管消声器", "个", 0.8, 2.0, 0.0),
    ("ac_copper_dn25", "空调铜管 DN25", "m", 1.1, 3.0, 0.1),
]

FIRE_ITEMS = [
    ("fire_pipe_dn65", "消防管道 DN65", "m", 1.0, 1.5, 0.1),
    ("fire_pipe_dn80", "消防管道 DN80", "m", 1.1, 1.8, 0.1),
    ("fire_pipe_dn100", "消防管道 DN100", "m", 1.3, 2.3, 0.1),
    ("fire_pipe_dn150", "消防管道 DN150", "m", 1.6, 3.5, 0.2),
    ("fire_hydrant_indoor", "室内消火栓", "套", 1.5, 3.0, 0.0),
    ("fire_hydrant_outdoor", "室外消火栓", "套", 2.0, 5.0, 0.5),
    ("sprinkler_head_pendant", "下垂型洒水喷头", "头", 0.4, 0.8, 0.0),
    ("sprinkler_head_sidewall", "边墙型洒水喷头", "头", 0.5, 1.0, 0.0),
    ("sprinkler_head_fast", "快速响应喷头", "头", 0.5, 1.2, 0.0),
    ("alarm_detector_smoke", "烟感探测器", "个", 0.4, 0.8, 0.0),
    ("alarm_detector_heat", "温感探测器", "个", 0.4, 0.7, 0.0),
    ("manual_alarm", "手动报警按钮", "个", 0.3, 0.6, 0.0),
    ("alarm_bell", "警铃", "个", 0.5, 0.8, 0.0),
    ("fire_control_panel", "火灾报警控制器", "台", 3.0, 12.0, 0.0),
    ("fire_pump_indoor", "室内消防泵", "台", 3.0, 0.0, 0.5),
    ("fire_pump_stabilizer", "稳压泵", "台", 2.0, 0.0, 0.3),
    ("fire_tank_18m3", "消防水箱 18m³", "座", 3.0, 8.0, 1.5),
    ("fire_tank_36m3", "消防水箱 36m³", "座", 4.5, 15.0, 2.0),
    ("extinguisher_4kg", "4kg干粉灭火器", "具", 0.1, 0.5, 0.0),
    ("extinguisher_5kg", "5kg干粉灭火器", "具", 0.1, 0.6, 0.0),
    ("extinguisher_co2", "CO₂灭火器", "具", 0.1, 0.8, 0.0),
    ("smoke_exhaust_duct", "防排烟风管", "m²", 1.5, 2.0, 0.3),
    ("smoke_exhaust_fan", "排烟风机", "台", 3.0, 0.0, 0.5),
    ("gas_extinguish_system", "气体灭火系统", "套", 10.0, 0.0, 2.0),
    ("fire_pipe_dn200", "消防管道 DN200", "m", 2.0, 5.0, 0.3),
    ("fire_pipe_dn250", "消防管道 DN250", "m", 2.3, 6.5, 0.3),
    ("sprinkler_concealed", "隐蔽式喷头", "头", 0.6, 1.5, 0.0),
    ("deluge_valve", "雨淋阀组", "套", 3.0, 8.0, 0.5),
    ("alarm_module", "报警模块", "个", 0.3, 0.5, 0.0),
    ("fire_phone", "消防电话插孔", "个", 0.3, 0.4, 0.0),
    ("fire_broadcast", "消防广播模块", "个", 0.5, 1.0, 0.0),
    ("fire_door_closer", "防火门闭门器", "套", 0.8, 2.0, 0.0),
    ("fire_door_monitor", "防火门监控器", "台", 1.0, 3.0, 0.0),
    ("foam_system", "泡沫灭火系统", "套", 8.0, 0.0, 1.5),
    ("fire_water_monitor", "消防水炮", "台", 2.5, 5.0, 0.5),
    ("fire_hose_reel", "消防软管卷盘", "套", 1.0, 2.0, 0.0),
    ("fire_escape_sign", "安全出口指示等", "套", 0.5, 1.0, 0.0),
    ("kitchen_fire_system", "厨房灭火装置", "套", 5.0, 8.0, 0.5),
]

WEAK_CURRENT_ITEMS = [
    ("cat5e_cable", "超五类双绞线", "m", 0.1, 0.3, 0.0),
    ("cat6_cable", "六类双绞线", "m", 0.12, 0.5, 0.0),
    ("fiber_cable_4", "4芯光缆", "m", 0.2, 1.0, 0.0),
    ("fiber_cable_12", "12芯光缆", "m", 0.25, 2.5, 0.0),
    ("coaxial_cable", "同轴电缆", "m", 0.1, 0.4, 0.0),
    ("information_outlet", "信息插座", "个", 0.3, 0.5, 0.0),
    ("network_cabinet_12u", "12U 网络机柜", "台", 2.0, 8.0, 0.0),
    ("network_cabinet_42u", "42U 网络机柜", "台", 4.0, 20.0, 0.3),
    ("switch_24port", "24口交换机", "台", 0.5, 0.0, 0.0),
    ("switch_48port", "48口交换机", "台", 0.8, 0.0, 0.0),
    ("camera_indoor", "室内监控摄像头", "台", 0.8, 2.0, 0.0),
    ("camera_outdoor", "室外监控摄像头", "台", 1.0, 3.0, 0.0),
    ("camera_dome", "半球摄像机", "台", 0.8, 2.5, 0.0),
    ("camera_ptz", "球型摄像机", "台", 1.5, 6.0, 0.0),
    ("nvr_8ch", "8路硬盘录像机", "台", 1.0, 0.0, 0.0),
    ("nvr_16ch", "16路硬盘录像机", "台", 1.2, 0.0, 0.0),
    ("nvr_32ch", "32路硬盘录像机", "台", 1.5, 0.0, 0.0),
    ("access_controller", "门禁控制器", "套", 1.0, 3.0, 0.0),
    ("card_reader", "读卡器", "个", 0.5, 1.5, 0.0),
    ("electric_lock", "电控锁", "把", 0.8, 2.0, 0.0),
    ("intercom_outdoor", "楼宇对讲门口机", "套", 1.5, 5.0, 0.0),
    ("intercom_indoor", "楼宇对讲室内分机", "套", 0.8, 2.5, 0.0),
    ("pa_speaker", "公共广播扬声器", "个", 0.5, 1.0, 0.0),
    ("pa_amplifier", "广播功放", "台", 1.0, 3.0, 0.0),
    ("satellite_tv_outlet", "有线电视插座", "个", 0.3, 0.5, 0.0),
    ("fiber_patch_panel", "光纤配线架", "台", 1.5, 3.0, 0.0),
    ("ups_small", "UPS 不间断电源（小）", "台", 1.0, 0.0, 0.0),
    ("ups_large", "UPS 不间断电源（大）", "台", 3.0, 0.0, 0.5),
    ("server_rack_install", "服务器上架安装", "台", 1.5, 0.0, 0.0),
    ("display_screen", "信息发布屏", "台", 1.5, 5.0, 0.0),
    ("parking_guidance", "停车引导系统探测器", "个", 0.8, 2.5, 0.0),
    ("ev_charger_7kw", "充电桩 7kW", "台", 2.0, 0.0, 0.3),
    ("ev_charger_60kw", "充电桩 60kW", "台", 4.0, 0.0, 0.8),
    ("intrusion_detector", "入侵探测器", "个", 0.5, 1.5, 0.0),
    ("video_wall", "视频拼接屏", "块", 2.0, 8.0, 0.0),
    ("fiber_cable_24", "24芯光缆", "m", 0.3, 4.0, 0.0),
]

OUTDOOR_ITEMS = [
    ("road_base_gravel", "级配碎石路面基层", "m²", 0.5, 1.2, 0.5),
    ("road_base_cement", "水泥稳定基层", "m²", 0.5, 1.5, 0.4),
    ("road_asphalt_thin", "沥青混凝土面层 40mm", "m²", 0.3, 1.5, 0.8),
    ("road_asphalt_thick", "沥青混凝土面层 60mm", "m²", 0.4, 2.2, 1.0),
    ("road_concrete", "混凝土路面 200mm", "m²", 0.5, 1.8, 0.5),
    ("sidewalk_tile", "人行道透水砖", "m²", 0.8, 1.2, 0.0),
    ("sidewalk_granite", "花岗岩人行道", "m²", 1.0, 3.0, 0.0),
    ("curb_granite", "花岗岩路缘石", "m", 0.6, 1.5, 0.0),
    ("curb_concrete", "混凝土路缘石", "m", 0.5, 0.8, 0.0),
    ("drainage_ditch", "排水沟", "m", 1.0, 1.0, 0.3),
    ("drainage_grating", "沟盖板", "m", 0.5, 1.5, 0.0),
    ("manhole_heavy", "重型检查井", "座", 5.0, 8.0, 1.0),
    ("manhole_light", "轻型检查井", "座", 3.0, 5.0, 0.5),
    ("boundary_wall_brick", "砖围墙", "m", 2.0, 2.0, 0.2),
    ("boundary_wall_cast", "现浇围墙", "m", 2.5, 4.0, 0.5),
    ("gate_sliding", "电动伸缩门", "樘", 3.0, 15.0, 0.5),
    ("gate_swing", "对开铁艺大门", "樘", 3.5, 12.0, 0.5),
    ("landscape_lawn", "草坪种植", "m²", 0.3, 0.5, 0.1),
    ("landscape_shrub", "灌木种植", "m²", 0.5, 1.0, 0.0),
    ("landscape_tree_small", "小乔木种植", "株", 1.0, 3.0, 0.2),
    ("landscape_tree_large", "大乔木种植", "株", 3.0, 15.0, 1.0),
    ("slope_protection", "护坡砌筑", "m²", 1.5, 2.0, 0.5),
    ("retaining_wall_stone", "浆砌石挡墙", "m³", 4.0, 5.0, 0.8),
    ("parking_marking", "停车位划线", "m²", 0.1, 0.3, 0.0),
    ("flagpole", "旗杆安装", "根", 2.0, 5.0, 0.5),
    ("bench_stone", "石材座凳", "套", 1.5, 3.0, 0.3),
    ("bollard", "防撞柱", "个", 0.8, 1.5, 0.2),
    ("speed_bump", "减速带", "m", 0.3, 0.8, 0.0),
    ("outdoor_light_pole", "庭院灯杆", "套", 2.5, 6.0, 0.5),
    ("underground_pipe_pe100", "室外埋地PE管 DN100", "m", 0.8, 1.5, 0.3),
    ("underground_pipe_pe200", "室外埋地PE管 DN200", "m", 1.0, 2.5, 0.5),
    ("rain_garden", "雨水花园", "m²", 0.8, 2.0, 0.2),
    ("permeable_pavement", "透水混凝土路面", "m²", 0.6, 2.0, 0.5),
    ("playground_rubber", "橡胶地块地面", "m²", 0.5, 2.5, 0.0),
]

SCAFFOLD_ITEMS = [
    ("comprehensive_multi", "综合脚手架 多层建筑", "m²", 0.3, 0.5, 0.2),
    ("comprehensive_high", "综合脚手架 高层建筑", "m²", 0.4, 0.6, 0.3),
    ("outer_wall_single", "外墙单排脚手架", "m²", 0.25, 0.4, 0.15),
    ("outer_wall_double", "外墙双排脚手架", "m²", 0.35, 0.6, 0.2),
    ("floor_full", "满堂脚手架", "m²", 0.4, 0.6, 0.2),
    ("cantilever", "悬挑脚手架", "m²", 0.5, 1.5, 0.3),
    ("climbing", "附着式升降脚手架", "m²", 0.3, 3.0, 0.5),
    ("safety_net_horizontal", "水平安全网", "m²", 0.1, 0.2, 0.0),
    ("safety_net_vertical", "立网", "m²", 0.1, 0.3, 0.0),
    ("temporary_power", "临时用电设施", "项", 0.0, 5.0, 0.0),
    ("temporary_water", "临时用水设施", "项", 0.0, 3.0, 0.0),
    ("temporary_road", "临时道路", "m²", 0.3, 1.0, 0.5),
    ("temporary_fence", "施工围挡", "m", 0.5, 2.5, 0.0),
    ("unloading_platform", "卸料平台", "座", 8.0, 15.0, 1.0),
    ("hoist_elevator", "施工电梯", "台月", 5.0, 0.0, 2.0),
    ("tower_crane", "塔式起重机", "台月", 15.0, 0.0, 10.0),
    ("material_hoist", "物料提升机", "台月", 3.0, 0.0, 1.5),
    ("pump_truck", "混凝土泵车", "台班", 2.0, 0.0, 8.0),
    ("pump_trailer", "混凝土拖泵", "台班", 1.5, 0.0, 6.0),
    ("scaffold_interior", "室内满堂脚手架 ≤ 3.6m", "m²", 0.35, 0.5, 0.15),
    ("scaffold_interior_high", "室内满堂脚手架 3.6-6m", "m²", 0.45, 0.7, 0.2),
    ("scaffold_decoration", "装饰装修脚手架", "m²", 0.3, 0.4, 0.15),
    ("concrete_curing", "混凝土养护设施", "m²", 0.05, 0.1, 0.0),
    ("winter_measures", "冬季施工措施", "m²", 0.05, 0.2, 0.0),
    ("rainy_measures", "雨季施工措施", "m²", 0.03, 0.15, 0.0),
]

DEMOLITION_ITEMS = [
    ("masonry_wall_demo", "砖墙拆除", "m³", 3.0, 0.0, 0.5),
    ("concrete_wall_demo", "混凝土墙拆除", "m³", 6.0, 0.0, 2.5),
    ("slab_demo", "混凝土板拆除", "m³", 5.5, 0.0, 2.0),
    ("beam_demo", "混凝土梁柱拆除", "m³", 7.0, 0.0, 3.0),
    ("floor_finish_demo", "楼地面装饰拆除", "m²", 0.5, 0.0, 0.0),
    ("wall_finish_demo", "墙面装饰拆除", "m²", 0.4, 0.0, 0.0),
    ("ceiling_demo", "吊顶拆除", "m²", 0.3, 0.0, 0.0),
    ("door_window_demo", "门窗拆除", "m²", 0.3, 0.0, 0.0),
    ("tile_demo", "瓷砖拆除", "m²", 0.4, 0.0, 0.0),
    ("roof_waterproof_demo", "屋面防水层拆除", "m²", 0.3, 0.0, 0.0),
    ("debris_cleaning", "建筑垃圾清理", "m³", 0.5, 0.0, 1.5),
    ("debris_transport_5km", "建筑垃圾外运 5km", "m³", 0.2, 0.0, 3.0),
    ("steel_structure_demo", "钢结构拆除", "t", 5.0, 0.0, 2.0),
    ("pipe_demo", "管道拆除", "m", 0.3, 0.0, 0.1),
    ("electrical_demo", "电气线路拆除", "m", 0.15, 0.0, 0.0),
    ("equipment_demo", "设备拆除", "台", 3.0, 0.0, 1.0),
    ("foundation_demo", "基础拆除", "m³", 6.0, 0.0, 3.0),
    ("curtain_wall_demo", "幕墙拆除", "m²", 0.8, 0.0, 0.3),
    ("scaffold_demo", "脚手架拆除", "m²", 0.2, 0.0, 0.1),
    ("fence_demo", "围墙拆除", "m", 1.0, 0.0, 0.5),
    ("asphalt_demo", "油面拆除", "m²", 0.3, 0.0, 0.5),
    ("debris_transport_10km", "建筑垃圾外运 10km", "m³", 0.2, 0.0, 4.5),
]

# ── New chapters ──────────────────────────────────────────────

STEEL_STRUCTURE_ITEMS = [
    ("h_beam_column", "H型钢柱 制安", "t", 8.0, 1.05, 3.0),
    ("h_beam", "H型钢梁 制安", "t", 7.5, 1.05, 2.8),
    ("box_column", "箱型钢柱 制安", "t", 10.0, 1.08, 3.5),
    ("steel_tube_column", "钢管柱 制安", "t", 9.0, 1.06, 3.2),
    ("steel_brace", "钢支撑 制安", "t", 7.0, 1.05, 2.5),
    ("steel_truss", "钢桁架 制安", "t", 12.0, 1.08, 4.0),
    ("steel_stair", "钢楼梯 制安", "t", 10.0, 1.06, 3.0),
    ("steel_platform", "钢平台 制安", "t", 8.5, 1.05, 2.8),
    ("steel_canopy", "钢雨篷 制安", "t", 9.0, 1.06, 3.0),
    ("purlin_c", "C型钢檩条 制安", "t", 6.0, 1.04, 2.0),
    ("purlin_z", "Z型钢檩条 制安", "t", 6.0, 1.04, 2.0),
    ("profiled_sheet_roof", "压型钢板屋面板", "m²", 0.6, 1.5, 0.2),
    ("profiled_sheet_wall", "压型钢板墙面板", "m²", 0.5, 1.3, 0.2),
    ("profiled_sheet_floor", "压型钢板楼承板", "m²", 0.7, 1.8, 0.3),
    ("stud_weld", "栓钉焊接", "个", 0.05, 0.1, 0.02),
    ("bolt_ordinary", "普通螺栓连接", "套", 0.1, 0.15, 0.0),
    ("bolt_high_strength", "高强度螺栓连接", "套", 0.15, 0.25, 0.0),
    ("bolt_friction", "高强螺栓（摩擦型）", "套", 0.18, 0.3, 0.0),
    ("weld_butt", "对接焊缝", "m", 0.5, 0.3, 0.2),
    ("weld_fillet", "角焊缝", "m", 0.4, 0.2, 0.15),
    ("steel_embed_plate", "预埋钢板", "kg", 0.03, 1.05, 0.0),
    ("steel_railing", "钢栏杆扶手", "m", 0.8, 1.5, 0.0),
    ("steel_grating", "钢格栅板", "m²", 0.5, 2.0, 0.1),
    ("steel_ladder", "钢爬梯", "m", 1.0, 2.0, 0.2),
    ("steel_grid", "钢网架 制安", "t", 15.0, 1.08, 5.0),
    ("steel_door_frame", "钢门框 制安", "t", 8.0, 1.05, 2.0),
    ("steel_painting_primer", "钢构底漆", "m²", 0.2, 0.3, 0.0),
    ("steel_painting_middle", "钢构中间漆", "m²", 0.15, 0.25, 0.0),
    ("steel_painting_finish", "钢构面漆", "m²", 0.15, 0.3, 0.0),
    ("fireproof_coating_thin", "薄型防火涂料", "m²", 0.3, 1.5, 0.0),
    ("fireproof_coating_thick", "厚型防火涂料", "m²", 0.5, 2.5, 0.1),
    ("steel_space_frame", "螺栓球网架 制安", "t", 14.0, 1.10, 4.5),
    ("steel_arch", "钢拱架 制安", "t", 13.0, 1.08, 4.0),
    ("tension_rod", "拉索/拉杆", "t", 10.0, 1.05, 3.0),
    ("steel_corbel", "钢牛腿 制安", "t", 9.0, 1.06, 3.0),
    ("steel_connector", "节点板 制安", "t", 8.0, 1.05, 2.5),
    ("shear_stud_group", "组合楼板栓钉群焊", "组", 0.3, 0.5, 0.1),
    ("steel_column_base", "钢柱脚锚栓安装", "套", 1.0, 2.0, 0.2),
    ("steel_sag_rod", "隅撑/系杆", "t", 6.5, 1.04, 2.0),
    ("steel_crane_beam", "钢吊车梁 制安", "t", 9.5, 1.06, 3.5),
]

PAINTING_ITEMS = [
    ("wood_primer", "木面底漆", "m²", 0.2, 0.3, 0.0),
    ("wood_varnish", "木面清漆", "m²", 0.25, 0.4, 0.0),
    ("wood_color_paint", "木面调和漆", "m²", 0.25, 0.35, 0.0),
    ("metal_primer", "金属面防锈底漆", "m²", 0.2, 0.3, 0.0),
    ("metal_enamel", "金属面磁漆", "m²", 0.2, 0.35, 0.0),
    ("metal_antirust", "金属面防腐漆", "m²", 0.25, 0.5, 0.0),
    ("wall_primer_inner", "内墙底漆", "m²", 0.15, 0.2, 0.0),
    ("wall_latex_inner", "内墙乳胶漆（二遍）", "m²", 0.2, 0.3, 0.0),
    ("wall_primer_outer", "外墙底漆", "m²", 0.2, 0.25, 0.0),
    ("wall_latex_outer", "外墙乳胶漆（二遍）", "m²", 0.25, 0.4, 0.0),
    ("wall_texture_paint", "外墙质感涂料", "m²", 0.35, 0.8, 0.0),
    ("wall_fluorocarbon", "氟碳漆", "m²", 0.3, 1.2, 0.0),
    ("floor_epoxy_primer", "地坪环氧底涂", "m²", 0.15, 0.5, 0.0),
    ("floor_epoxy_middle", "地坪环氧中涂", "m²", 0.2, 0.8, 0.0),
    ("floor_epoxy_finish", "地坪环氧面涂", "m²", 0.2, 0.6, 0.0),
    ("floor_epoxy_mortar", "地坪环氧砂浆层", "m²", 0.3, 1.2, 0.0),
    ("fireproof_steel_thin_p", "薄涂型钢结构防火涂料", "m²", 0.3, 1.5, 0.0),
    ("fireproof_steel_thick_p", "厚涂型钢结构防火涂料", "m²", 0.5, 2.5, 0.1),
    ("pipe_antirust_paint", "管道防锈漆", "m²", 0.2, 0.3, 0.0),
    ("pipe_color_mark", "管道色标漆", "m²", 0.15, 0.2, 0.0),
    ("floor_pu_coating", "聚氨酯地坪涂装", "m²", 0.25, 0.9, 0.0),
    ("wall_diatomite", "硅藻泥涂装", "m²", 0.4, 1.5, 0.0),
    ("anti_mold_paint", "防霉涂料", "m²", 0.2, 0.4, 0.0),
    ("elastic_paint", "弹性涂料", "m²", 0.3, 0.6, 0.0),
    ("marking_paint", "标识标线漆", "m²", 0.1, 0.2, 0.0),
    ("ceiling_latex", "天棚乳胶漆", "m²", 0.2, 0.3, 0.0),
    ("stair_paint", "楼梯间涂料", "m²", 0.25, 0.35, 0.0),
    ("garage_epoxy", "车库地坑漆", "m²", 0.2, 0.7, 0.0),
    ("waterproof_paint", "防水涂料涂装", "m²", 0.3, 0.8, 0.0),
    ("anticorr_pipe", "管道防腐漆（二度）", "m²", 0.25, 0.5, 0.0),
    ("floor_polyurea", "聚脲地坡涂装", "m²", 0.3, 1.5, 0.0),
    ("metal_galvanize", "金属面镀锌处理", "m²", 0.3, 0.8, 0.1),
    ("wood_stain", "木材着色剂", "m²", 0.2, 0.3, 0.0),
    ("wood_wax_oil", "木蜡油涂装", "m²", 0.2, 0.5, 0.0),
    ("concrete_sealer", "混凝土密封剂", "m²", 0.1, 0.3, 0.0),
    ("concrete_stain", "混凝土着色剂", "m²", 0.15, 0.4, 0.0),
    ("brick_sealer", "砖面防护剂", "m²", 0.1, 0.2, 0.0),
    ("stone_sealer", "石材防护剂", "m²", 0.1, 0.3, 0.0),
    ("roof_reflective", "屋面反射涂料", "m²", 0.2, 0.5, 0.0),
    ("pool_paint", "水池专用漆", "m²", 0.3, 0.8, 0.0),
    ("antistatic_paint", "防静电涂料", "m²", 0.25, 0.7, 0.0),
    ("cleanroom_paint", "洁净室涂料", "m²", 0.3, 1.0, 0.0),
    ("anti_graffiti", "防涂鸦涂料", "m²", 0.2, 0.6, 0.0),
    ("intumescent_paint", "膊胀型防火涂料", "m²", 0.3, 1.8, 0.0),
    ("thermal_barrier_paint", "隔热涂料", "m²", 0.2, 0.6, 0.0),
    ("nano_paint", "纳米自洁涂料", "m²", 0.2, 0.8, 0.0),
    ("zinc_rich_primer", "富锌底漆", "m²", 0.2, 0.5, 0.0),
    ("epoxy_coal_tar", "环氧煤沫沥青漆", "m²", 0.25, 0.6, 0.0),
    ("chlorinated_rubber", "氯化橡胶防腐漆", "m²", 0.25, 0.5, 0.0),
]

ELEVATOR_ITEMS = [
    ("passenger_1000kg", "客梯 1000kg 安装", "台", 60.0, 0.0, 15.0),
    ("passenger_1350kg", "客梯 1350kg 安装", "台", 65.0, 0.0, 16.0),
    ("passenger_1600kg", "客梯 1600kg 安装", "台", 70.0, 0.0, 18.0),
    ("freight_2000kg", "货梯 2000kg 安装", "台", 80.0, 0.0, 20.0),
    ("freight_3000kg", "货梯 3000kg 安装", "台", 90.0, 0.0, 22.0),
    ("freight_5000kg", "货梯 5000kg 安装", "台", 100.0, 0.0, 25.0),
    ("escalator_30deg", "自动扶梯 30°", "台", 50.0, 0.0, 12.0),
    ("escalator_35deg", "自动扶梯 35°", "台", 55.0, 0.0, 13.0),
    ("moving_walkway", "自动人行道", "台", 45.0, 0.0, 10.0),
    ("dumbwaiter", "杂物电梯", "台", 25.0, 0.0, 5.0),
    ("car_elevator", "汽车电梯", "台", 120.0, 0.0, 30.0),
    ("elevator_shaft_door", "电梯厅门", "樘", 2.0, 3.0, 0.0),
    ("elevator_guide_rail", "电梯导轨安装", "m", 1.0, 2.0, 0.3),
    ("elevator_buffer", "电梯缓冲器", "套", 1.5, 2.5, 0.0),
    ("elevator_control_cab", "电梯控制柜", "台", 3.0, 0.0, 0.0),
    ("bed_elevator", "担架电梯 1600kg", "台", 70.0, 0.0, 18.0),
    ("panoramic_elevator", "观光电梯", "台", 75.0, 0.0, 20.0),
    ("firefighter_elevator", "消防电梯", "台", 80.0, 0.0, 22.0),
    ("hydraulic_elevator", "液压电梯", "台", 45.0, 0.0, 8.0),
    ("mrl_elevator_1000", "无机房电梯 1000kg", "台", 55.0, 0.0, 12.0),
    ("mrl_elevator_1350", "无机房电梯 1350kg", "台", 60.0, 0.0, 14.0),
    ("mrl_elevator_1600", "无机房电梯 1600kg", "台", 65.0, 0.0, 16.0),
    ("elevator_pit_waterproof", "电梯底坑防水", "台", 1.5, 2.0, 0.0),
    ("elevator_machine_room", "机房设备安装", "台", 5.0, 0.0, 1.0),
    ("elevator_signal_sys", "电梯信号系统", "台", 2.0, 0.0, 0.0),
    ("elevator_intercom", "电梯对讲系统", "台", 1.0, 0.0, 0.0),
    ("elevator_cctv", "电梯监控系统", "台", 1.5, 2.0, 0.0),
    ("elevator_ventilation", "电梯井道通风", "台", 1.0, 1.5, 0.2),
    ("elevator_door_device", "电梯门套装置", "樘", 1.5, 2.0, 0.0),
    ("stairlift", "座椅电梯", "台", 20.0, 0.0, 3.0),
    ("platform_lift", "无障碍升降平台", "台", 15.0, 0.0, 2.5),
    ("goods_hoist_500", "货梯 500kg", "台", 30.0, 0.0, 6.0),
    ("goods_hoist_1000", "货梯 1000kg", "台", 40.0, 0.0, 8.0),
    ("scissor_lift", "剪叉式升降平台", "台", 10.0, 0.0, 2.0),
    ("escalator_heavy", "重型自动扶梯", "台", 65.0, 0.0, 15.0),
    ("inclined_elevator", "斜行电梯", "台", 50.0, 0.0, 10.0),
    ("home_elevator", "家用电梯", "台", 35.0, 0.0, 6.0),
    ("explosion_proof_elev", "防爆电梯", "台", 90.0, 0.0, 25.0),
    ("clean_room_elevator", "洁净电梯", "台", 85.0, 0.0, 22.0),
]

PIPE_INSULATION_ITEMS = [
    ("glass_wool_dn25", "管道保温 玻璃棉 DN25", "m", 0.3, 0.5, 0.0),
    ("glass_wool_dn50", "管道保温 玻璃棉 DN50", "m", 0.4, 0.7, 0.0),
    ("glass_wool_dn80", "管道保温 玻璃棉 DN80", "m", 0.5, 0.9, 0.0),
    ("glass_wool_dn100", "管道保温 玻璃棉 DN100", "m", 0.6, 1.1, 0.0),
    ("glass_wool_dn150", "管道保温 玻璃棉 DN150", "m", 0.7, 1.5, 0.0),
    ("rubber_foam_dn25", "管道保温 橡塑 DN25", "m", 0.25, 0.6, 0.0),
    ("rubber_foam_dn50", "管道保温 橡塑 DN50", "m", 0.35, 0.8, 0.0),
    ("rubber_foam_dn80", "管道保温 橡塑 DN80", "m", 0.45, 1.0, 0.0),
    ("rubber_foam_dn100", "管道保温 橡塑 DN100", "m", 0.55, 1.3, 0.0),
    ("pu_foam_dn50", "管道保温 聚氨酯 DN50", "m", 0.4, 1.0, 0.0),
    ("pu_foam_dn80", "管道保温 聚氨酯 DN80", "m", 0.5, 1.3, 0.0),
    ("pu_foam_dn100", "管道保温 聚氨酯 DN100", "m", 0.6, 1.6, 0.0),
    ("pu_foam_dn150", "管道保温 聚氨酯 DN150", "m", 0.7, 2.0, 0.0),
    ("rock_wool_pipe_dn50", "管道保温 岩棉管壳 DN50", "m", 0.4, 0.8, 0.0),
    ("rock_wool_pipe_dn80", "管道保温 岩棉管壳 DN80", "m", 0.5, 1.0, 0.0),
    ("rock_wool_pipe_dn100", "管道保温 岩棉管壳 DN100", "m", 0.6, 1.2, 0.0),
    ("rock_wool_pipe_dn150", "管道保温 岩棉管壳 DN150", "m", 0.7, 1.6, 0.0),
    ("aluminum_jacket_dn50", "铝皮保护层 DN50", "m", 0.3, 0.8, 0.0),
    ("aluminum_jacket_dn100", "铝皮保护层 DN100", "m", 0.4, 1.2, 0.0),
    ("aluminum_jacket_dn150", "铝皮保护层 DN150", "m", 0.5, 1.6, 0.0),
    ("pipe_anticorr_dn25", "管道防腐 底漆 DN25", "m", 0.15, 0.2, 0.0),
    ("pipe_anticorr_dn50", "管道防腐 底漆 DN50", "m", 0.2, 0.3, 0.0),
    ("pipe_anticorr_dn100", "管道防腐 底漆 DN100", "m", 0.25, 0.4, 0.0),
    ("pipe_anticorr_dn150", "管道防腐 底漆 DN150", "m", 0.3, 0.5, 0.0),
    ("valve_insulation_dn50", "阀门保温 DN50", "个", 0.5, 1.0, 0.0),
    ("valve_insulation_dn100", "阀门保温 DN100", "个", 0.8, 1.5, 0.0),
    ("valve_insulation_dn150", "阀门保温 DN150", "个", 1.0, 2.0, 0.0),
    ("equipment_insulation_s", "设备保温（小型）", "m²", 0.5, 1.0, 0.0),
    ("equipment_insulation_l", "设备保温（大型）", "m²", 0.7, 1.5, 0.1),
    ("duct_insulation_outer", "风管外保温", "m²", 0.4, 0.8, 0.0),
    ("glass_wool_dn200", "管道保温 玻璃棉 DN200", "m", 0.8, 2.0, 0.0),
    ("rubber_foam_dn150", "管道保温 橡塞 DN150", "m", 0.65, 1.6, 0.0),
    ("rubber_foam_dn200", "管道保温 橡塞 DN200", "m", 0.75, 2.0, 0.0),
    ("pu_foam_dn200", "管道保温 聚氨酯 DN200", "m", 0.8, 2.5, 0.0),
    ("pu_foam_dn250", "管道保温 聚氨酯 DN250", "m", 0.9, 3.0, 0.0),
    ("rock_wool_pipe_dn200", "管道保温 岩棉管壳 DN200", "m", 0.8, 2.0, 0.0),
    ("aluminum_jacket_dn200", "铝皮保护层 DN200", "m", 0.6, 2.0, 0.0),
    ("aluminum_jacket_dn250", "铝皮保护层 DN250", "m", 0.7, 2.5, 0.0),
    ("pipe_anticorr_dn200", "管道防腐 底漆 DN200", "m", 0.35, 0.6, 0.0),
    ("pipe_anticorr_dn250", "管道防腐 底漆 DN250", "m", 0.4, 0.7, 0.0),
    ("valve_insulation_dn200", "阀门保温 DN200", "个", 1.2, 2.5, 0.0),
    ("equipment_insulation_m", "设备保温（中型）", "m²", 0.6, 1.2, 0.0),
    ("flange_insulation_dn50", "法兰保温 DN50", "个", 0.4, 0.6, 0.0),
    ("flange_insulation_dn100", "法兰保温 DN100", "个", 0.6, 1.0, 0.0),
    ("flange_insulation_dn150", "法兰保温 DN150", "个", 0.8, 1.5, 0.0),
    ("tank_insulation", "水箱保温", "m²", 0.5, 1.0, 0.0),
    ("duct_insulation_inner", "风管内保温", "m²", 0.5, 1.0, 0.0),
    ("cold_pipe_anticondensation", "冷管防凝露", "m²", 0.4, 0.7, 0.0),
    ("steam_pipe_insulation", "蒸汽管保温", "m", 0.7, 1.5, 0.0),
    ("exhaust_pipe_insulation", "排烟管保温", "m", 0.6, 1.2, 0.0),
]

PREFAB_ITEMS = [
    ("pc_wall_ext_200", "预制外墙板 200mm", "m²", 2.0, 0.0, 1.5),
    ("pc_wall_ext_250", "预制外墙板 250mm", "m²", 2.2, 0.0, 1.6),
    ("pc_wall_int_120", "预制内墙板 120mm", "m²", 1.5, 0.0, 1.0),
    ("pc_wall_int_200", "预制内墙板 200mm", "m²", 1.8, 0.0, 1.2),
    ("pc_slab_120", "预制叠合板 120mm", "m²", 1.8, 0.0, 1.3),
    ("pc_slab_150", "预制叠合板 150mm", "m²", 2.0, 0.0, 1.4),
    ("pc_beam", "预制梳 安装", "m", 1.5, 0.0, 2.0),
    ("pc_column", "预制柱 安装", "根", 3.0, 0.0, 3.0),
    ("pc_stair_flight", "预制楼梯段", "段", 2.5, 0.0, 2.0),
    ("pc_balcony", "预制阳台板", "块", 2.0, 0.0, 1.8),
    ("pc_air_con_slab", "预制空调板", "块", 1.5, 0.0, 1.2),
    ("pc_bay_window", "预制飘窗", "樘", 2.0, 0.0, 1.5),
    ("pc_parapet", "预制女儿墙", "m", 1.0, 0.0, 1.0),
    ("pc_sandwich_wall", "预制夹心保温墙板", "m²", 2.5, 0.0, 1.8),
    ("pc_cladding", "预制装饰挂板", "m²", 1.5, 0.0, 1.2),
    ("grout_sleeve", "套筒灌浆连接", "个", 0.3, 0.5, 0.0),
    ("grout_material", "套筒灌浆料", "L", 0.05, 0.2, 0.0),
    ("pc_joint_sealant", "接缝密封胶", "m", 0.2, 0.3, 0.0),
    ("pc_wet_joint", "现浇湿接缝", "m", 0.8, 0.5, 0.2),
    ("pc_dry_joint", "干式连接接缝", "m", 0.5, 0.8, 0.1),
    ("embed_channel", "预埋槽道", "m", 0.3, 0.5, 0.0),
    ("embed_plate_s", "预埋件铁板（小）", "个", 0.2, 0.3, 0.0),
    ("embed_plate_l", "预埋件铁板（大）", "个", 0.4, 0.8, 0.0),
    ("pc_transport_wall", "预制墙板运输", "m²", 0.1, 0.0, 0.5),
    ("pc_transport_slab", "预制楼板运输", "m²", 0.1, 0.0, 0.4),
    ("pc_transport_stair", "预制楼梯运输", "段", 0.2, 0.0, 0.8),
    ("pc_hoist_wall", "预制墙板吃装", "块", 0.8, 0.0, 1.5),
    ("pc_hoist_slab", "预制楼板吃装", "块", 0.6, 0.0, 1.2),
    ("pc_quality_check", "预制构件进场检验", "批", 1.0, 0.0, 0.0),
    ("pc_temporary_support", "临时支撑体系", "m²", 0.3, 0.8, 0.2),
    ("aac_panel_ext", "ALC板外墙", "m²", 1.2, 2.0, 0.3),
    ("aac_panel_int", "ALC板内墙", "m²", 1.0, 1.8, 0.2),
    ("aac_panel_roof", "ALC板屋面", "m²", 1.3, 2.2, 0.3),
    ("hollow_core_slab", "预应力空心板", "m²", 1.5, 0.0, 1.0),
    ("precast_girder", "预制T形梳", "根", 5.0, 0.0, 4.0),
    ("steel_mesh_panel", "钢丝网架珠光体板", "m²", 1.0, 1.5, 0.2),
    ("grc_panel_prefab", "GRC幕墙板", "m²", 1.5, 4.0, 0.3),
    ("uhpc_panel", "UHPC装饰板", "m²", 2.0, 6.0, 0.3),
    ("pc_duct_sleeve", "预留管道套管", "个", 0.2, 0.3, 0.0),
    ("pc_electrical_box", "预埋电气接线盒", "个", 0.15, 0.2, 0.0),
]

# ── Generator functions ─────────────────────────────────────────

def gen_concrete() -> list[tuple]:
    """D-D concrete: member × grade."""
    items = []
    grade_factor_mat = {g: 0.85 + 0.05 * i for i, g in enumerate(CONCRETE_GRADES)}  # C15→0.85, C50→1.2
    grade_factor_labor = {g: 1.0 + 0.02 * i for i, g in enumerate(CONCRETE_GRADES)}
    for si, (mkey, mname, unit, lbase, mbase, mcbase) in enumerate(CONCRETE_MEMBERS, start=1):
        for gi, grade in enumerate(CONCRETE_GRADES, start=1):
            code = f"D-D{si:02d}{gi:02d}"
            name = f"{mname} {grade}"
            labor = round(lbase * grade_factor_labor[grade], 2)
            mat = round(mbase * grade_factor_mat[grade], 2)
            mach = round(mcbase, 2)
            items.append((code, name, unit, labor, mat, mach,
                          "混凝土浇筑、振捣、养护、模板维护", "适用一般工业与民用建筑现浇混凝土", "混凝土工程"))
    return items


def gen_rebar() -> list[tuple]:
    """D-E rebar: member × spec."""
    items = []
    for mi, (mkey, mname) in enumerate(REBAR_MEMBERS, start=1):
        for si, (skey, sname, labor, mat, mach) in enumerate(REBAR_SPECS, start=1):
            code = f"D-E{mi:02d}{si:02d}"
            name = f"{mname} {sname}"
            items.append((code, name, "t", labor, mat, mach,
                          "钢筋制作、安装、绑扎、定位",
                          f"适用{mname}用{sname}钢筋", "钢筋工程"))
    return items


def gen_formwork() -> list[tuple]:
    """D-F formwork: member × type."""
    items = []
    for mi, (mkey, mname, unit, lbase, mbase, mcbase) in enumerate(FORMWORK_MEMBERS, start=1):
        for ti, (tkey, tsuffix, mmul, lmul) in enumerate(FORMWORK_TYPES, start=1):
            code = f"D-F{mi:02d}{ti:02d}"
            name = f"{mname}（{tsuffix}）"
            labor = round(lbase * lmul, 2)
            mat = round(mbase * mmul, 2)
            mach = mcbase
            items.append((code, name, unit, labor, mat, mach,
                          "模板制作、安装、拆除、周转",
                          f"适用{mname}采用{tsuffix}", "模板工程"))
    return items


def gen_masonry() -> list[tuple]:
    """D-C masonry: type × thickness × mortar."""
    items = []
    for ti, (tkey, tname, unit, lbase, mbase, mcbase) in enumerate(MASONRY_TYPES, start=1):
        for thi, (thkey, thname, factor) in enumerate(MASONRY_THICKNESSES, start=1):
            for moi, (mokey, moname, mofactor) in enumerate(MASONRY_MORTAR_TYPES, start=1):
                code = f"D-C{ti:02d}{thi:02d}{moi}"
                name = f"{tname} 厚{thname}（{moname}）"
                items.append((code, name, unit, round(lbase * factor * mofactor, 2), round(mbase * factor, 2), mcbase,
                              "砌体砌筑、勾缝、钢筋网片铺设",
                              f"适用厚{thname}的{tname}（{moname}）", "砌筑工程"))
    return items


def gen_plastering() -> list[tuple]:
    """D-H plastering: part × mortar."""
    items = []
    for pi, (pkey, pname, unit, lbase, mbase, mcbase) in enumerate(PLASTER_PARTS, start=1):
        for mi, (mkey, msuffix, mmul) in enumerate(PLASTER_MORTARS, start=1):
            code = f"D-H1{pi:02d}{mi:02d}"
            name = f"{pname}（{msuffix}）"
            items.append((code, name, unit, lbase, round(mbase * mmul, 2), mcbase,
                          "基层处理、抹灰、压光、养护",
                          f"适用{pname}采用{msuffix}", "装饰装修-抹灰"))
    return items


def gen_floor() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(FLOOR_TYPES, start=1):
        code = f"D-J{i:03d}"
        items.append((code, name, unit, l, m, mc, "基层处理、铺设、填缝、清洁", f"适用于{name}做法", "楼地面工程"))
    return items


def gen_wall_finish() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(WALL_FINISH_TYPES, start=1):
        code = f"D-H2{i:03d}"
        items.append((code, name, unit, l, m, mc, "基层处理、批嵌、装饰层施工", f"适用{name}", "装饰装修-墙面"))
    return items


def gen_ceiling() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(CEILING_TYPES, start=1):
        code = f"D-H3{i:03d}"
        items.append((code, name, unit, l, m, mc, "龙骨安装、面板铺装、收边", f"适用{name}", "装饰装修-吊顶"))
    return items


def gen_door_window() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(DOOR_WINDOW_TYPES, start=1):
        code = f"D-I{i:03d}"
        items.append((code, name, unit, l, m, mc, "洞口处理、门窗安装、五金配件", f"适用{name}", "门窗工程"))
    return items


def gen_waterproof() -> list[tuple]:
    """D-G1 waterproof: material × part × layer."""
    items = []
    for mi, (mkey, mname, lbase, mbase, mcbase) in enumerate(WATERPROOF_MATERIALS, start=1):
        for pi, (pkey, pname) in enumerate(WATERPROOF_PARTS, start=1):
            part_factor_mat = {"roof": 1.0, "bathroom": 0.9, "basement_floor": 1.15,
                               "basement_wall": 1.1, "balcony": 0.9, "kitchen": 0.85,
                               "outer_wall": 1.05}[pkey]
            for li, (lkey, lname, lfactor) in enumerate(WATERPROOF_LAYERS, start=1):
                code = f"D-G1{mi:02d}{pi:02d}{li}"
                name = f"{pname} {mname}（{lname}）"
                items.append((code, name, "m²", round(lbase * lfactor, 2),
                              round(mbase * part_factor_mat * lfactor, 2), mcbase,
                              "基层清理、附加层、大面施工、保护层",
                              f"适用{pname}采用{mname}（{lname}）", "防水工程"))
    return items


def gen_insulation() -> list[tuple]:
    """D-G2 insulation: type × part × thickness."""
    items = []
    for mi, (mkey, mname, lbase, mbase, mcbase) in enumerate(INSULATION_TYPES, start=1):
        for pi, (pkey, pname) in enumerate(INSULATION_PARTS, start=1):
            for ti, (tkey, tname, tfactor) in enumerate(INSULATION_THICKNESSES, start=1):
                code = f"D-G2{mi:02d}{pi}{ti}"
                name = f"{pname} {mname} {tname}"
                items.append((code, name, "m²", round(lbase * tfactor, 2),
                              round(mbase * tfactor, 2), mcbase,
                              "基层处理、粘贴/固定、抗裂网、找平",
                              f"适用{pname}采用{mname} 厚度{tname}", "保温工程"))
    return items


def gen_earthwork() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(EARTHWORK_ITEMS, start=1):
        code = f"D-A{i:03d}"
        items.append((code, name, unit, l, m, mc, "开挖/回填/运输/夯实等", f"适用{name}工况", "土石方工程"))
    return items


def gen_piles() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(PILE_ITEMS, start=1):
        code = f"D-B{i:03d}"
        items.append((code, name, unit, l, m, mc, "桩位测量、成孔/打桩、钢筋笼、灌注或压入", f"适用{name}", "地基与桩基工程"))
    return items


def gen_plumbing() -> list[tuple]:
    """D-K1 plumbing: pipe × size × method."""
    items = []
    for ti, (tkey, tname, lbase, mbase, mcbase) in enumerate(PLUMBING_PIPES, start=1):
        for si, (skey, sname, sfactor) in enumerate(PLUMBING_SIZES, start=1):
            for mi, (mkey, mname, mfactor) in enumerate(PLUMBING_METHODS, start=1):
                code = f"D-K1{ti:02d}{si:02d}{mi}"
                name = f"{tname} {sname}（{mname}）"
                items.append((code, name, "m",
                              round(lbase * sfactor * mfactor, 2),
                              round(mbase * sfactor, 2), mcbase,
                              "管道敷设、切割、连接、试压",
                              f"适用{sname}的{tname}（{mname}）", "给排水-管道"))
    # Fixtures
    for i, (k, name, unit, l, m, mc) in enumerate(PLUMBING_FIXTURES, start=1):
        code = f"D-K2{i:03d}"
        items.append((code, name, unit, l, m, mc, "附件/设备安装、调试", f"适用{name}", "给排水-附件设备"))
    return items


def gen_electrical() -> list[tuple]:
    items = []
    for i, (k, name, l, m, mc) in enumerate(ELECTRICAL_CONDUITS, start=1):
        code = f"D-L1{i:03d}"
        items.append((code, name, "m", l, m, mc, "定位、预埋、敷设", f"适用{name}", "电气-配管"))
    for i, (k, name, l, m, mc) in enumerate(ELECTRICAL_CABLES, start=1):
        code = f"D-L2{i:03d}"
        items.append((code, name, "m", l, m, mc, "线缆敷设、穿管、接线", f"适用{name}", "电气-线缆"))
    for i, (k, name, unit, l, m, mc) in enumerate(ELECTRICAL_FIXTURES, start=1):
        code = f"D-L3{i:03d}"
        items.append((code, name, unit, l, m, mc, "设备/灯具/插座安装、调试", f"适用{name}", "电气-设备器具"))
    return items


def gen_hvac() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(HVAC_ITEMS, start=1):
        code = f"D-M{i:03d}"
        items.append((code, name, unit, l, m, mc, "设备/管道安装、保温、调试", f"适用{name}", "暖通空调工程"))
    return items


def gen_fire() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(FIRE_ITEMS, start=1):
        code = f"D-N{i:03d}"
        items.append((code, name, unit, l, m, mc, "消防管道/设备安装、报警调试", f"适用{name}", "消防工程"))
    return items


def gen_weak_current() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(WEAK_CURRENT_ITEMS, start=1):
        code = f"D-P{i:03d}"
        items.append((code, name, unit, l, m, mc, "线缆敷设、设备安装、系统调试", f"适用{name}", "弱电智能化"))
    return items


def gen_outdoor() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(OUTDOOR_ITEMS, start=1):
        code = f"D-R{i:03d}"
        items.append((code, name, unit, l, m, mc, "测量放线、铺设/砌筑/种植", f"适用{name}", "室外工程"))
    return items


def gen_scaffold() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(SCAFFOLD_ITEMS, start=1):
        code = f"D-S{i:03d}"
        items.append((code, name, unit, l, m, mc, "搭设、拆除、维护、租赁", f"适用{name}", "脚手架及措施"))
    return items


def gen_demolition() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(DEMOLITION_ITEMS, start=1):
        code = f"D-T{i:03d}"
        items.append((code, name, unit, l, m, mc, "拆除、清理、外运", f"适用{name}", "拆除工程"))
    return items


def gen_steel_structure() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(STEEL_STRUCTURE_ITEMS, start=1):
        code = f"D-U{i:03d}"
        items.append((code, name, unit, l, m, mc, "钢构件制作、运输、吊装、焊接/栓接、涂装", f"适用{name}", "钢结构工程"))
    return items


def gen_painting() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(PAINTING_ITEMS, start=1):
        code = f"D-V{i:03d}"
        items.append((code, name, unit, l, m, mc, "表面处理、底涂、面涂、养护", f"适用{name}", "涂料涂装工程"))
    return items


def gen_elevator() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(ELEVATOR_ITEMS, start=1):
        code = f"D-W{i:03d}"
        items.append((code, name, unit, l, m, mc, "设备就位、导轨安装、调试验收", f"适用{name}", "电梯安装工程"))
    return items


def gen_pipe_insulation() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(PIPE_INSULATION_ITEMS, start=1):
        code = f"D-X{i:03d}"
        items.append((code, name, unit, l, m, mc, "管道/设备保温、防腐、保护层施工", f"适用{name}", "管道保温防腐"))
    return items


def gen_prefab() -> list[tuple]:
    items = []
    for i, (k, name, unit, l, m, mc) in enumerate(PREFAB_ITEMS, start=1):
        code = f"D-Y{i:03d}"
        items.append((code, name, unit, l, m, mc, "预制构件生产、运输、吃装、灌浆连接", f"适用{name}", "预制装配式"))
    return items


# ── Main ────────────────────────────────────────────────────────

def build_all() -> list[tuple]:
    generators = [
        ("土石方", gen_earthwork),
        ("桩基", gen_piles),
        ("砌筑", gen_masonry),
        ("混凝土", gen_concrete),
        ("钢筋", gen_rebar),
        ("模板", gen_formwork),
        ("防水", gen_waterproof),
        ("保温", gen_insulation),
        ("抹灰", gen_plastering),
        ("楼地面", gen_floor),
        ("墙面装饰", gen_wall_finish),
        ("吊顶", gen_ceiling),
        ("门窗", gen_door_window),
        ("给排水", gen_plumbing),
        ("电气", gen_electrical),
        ("暖通", gen_hvac),
        ("消防", gen_fire),
        ("弱电", gen_weak_current),
        ("室外", gen_outdoor),
        ("脚手架", gen_scaffold),
        ("拆除", gen_demolition),
        ("钢结构", gen_steel_structure),
        ("涂料涂装", gen_painting),
        ("电梯", gen_elevator),
        ("管道保温", gen_pipe_insulation),
        ("预制装配式", gen_prefab),
    ]
    all_items: list[tuple] = []
    stats: list[tuple[str, int]] = []
    for label, fn in generators:
        got = fn()
        stats.append((label, len(got)))
        all_items.extend(got)
    print("\n── 生成统计 ──")
    for label, n in stats:
        print(f"  {label:8s} {n:5d} 条")
    print(f"  {'合计':8s} {len(all_items):5d} 条\n")
    return all_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--append", action="store_true", help="不清空现有数据，只追加新条目")
    parser.add_argument("--dry-run", action="store_true", help="只生成不入库")
    args = parser.parse_args()

    all_items = build_all()

    # De-dup within the generated batch (code should already be unique)
    seen_codes: set[str] = set()
    dedup: list[tuple] = []
    dup_count = 0
    for row in all_items:
        code = row[0]
        if code in seen_codes:
            dup_count += 1
            continue
        seen_codes.add(code)
        dedup.append(row)
    if dup_count:
        print(f"⚠️  批次内重复 code 已去重: {dup_count} 条")

    if args.dry_run:
        print("🔍 dry-run: 未写入数据库。")
        return

    db = SessionLocal()
    try:
        if not args.append:
            print("🗑️  清空旧绑定 / 计算结果 / 定额 ...")
            db.query(LineItemQuotaBinding).delete()
            db.query(CalcResult).delete()
            db.execute(BoqItem.__table__.update().values(is_dirty=1))
            db.query(QuotaItem).delete()
            db.commit()

        existing_codes = {c for (c,) in db.query(QuotaItem.quota_code).all()}
        inserted = 0
        skipped = 0
        for code, name, unit, labor, mat, mach, work_content, applicable_scope, chapter in dedup:
            if code in existing_codes:
                skipped += 1
                continue
            item = QuotaItem(
                quota_code=code,
                name=name,
                unit=unit,
                labor_qty=labor,
                material_qty=mat,
                machine_qty=mach,
                work_content=work_content,
                applicable_scope=applicable_scope,
                chapter=chapter,
                version="2024-批量生成",
                base_price=0.0,
            )
            db.add(item)
            inserted += 1
            if inserted % 200 == 0:
                db.commit()
        db.commit()

        total = db.query(QuotaItem).count()
        print(f"\n✅ 新插入 {inserted} 条，跳过 {skipped} 条（code 已存在）")
        print(f"✅ 定额库总计: {total} 条")
    finally:
        db.close()


if __name__ == "__main__":
    main()
