export interface Tower {
  site_name: string;
  height_m: number;
  top_width_m: number;
  bot_width_m: number;
  total_nodes: number;
  total_members: number;
}

export interface Geometry {
  nodes: { id: number; x: number; y: number; z: number; support: boolean }[];
  segments: number[][];
}

export interface LibraryDeviceInput {
  category: string;
  device_name: string;
  shape_type: string;
  dim_m: number;
  mass_kg: number;
  af_m2: number;
  asf_m2: number;
  ca_factor?: number | null;
  remark?: string;
}

export interface LibraryDevice extends LibraryDeviceInput {
  device_id: number;
  ca_factor: number;
  epa_m2: number;
  remark: string;
}

export type DeviceStatus = "EXISTING" | "PROPOSED";
export type TowerFace = "A" | "B" | "C" | "D";
export type UserRole = "engineer" | "devops" | "pm";

export interface DeviceSuggestion {
  device_name: string;
  category: string;
  shape_type: string;
  dim_m: number;
  mass_kg: number;
  af_m2: number;
  asf_m2: number;
  epa_m2: number;
  similarity_pct: number;
  reason: string;
}

export interface SiteDeviceInput {
  status: DeviceStatus;
  tenant: string;
  device_name: string;
  mounting_name: string | null;
  elev_z_m: number;
  qty: number;
}

export interface SiteDevice extends SiteDeviceInput {
  id: number;
  in_library: boolean;
  epa_m2: number | null;
  mass_kg?: number | null;
  shape_type?: string;
  length_m?: number;
  width_m?: number;
  depth_m?: number;
  face?: TowerFace;
  x_m?: number;
  y_m?: number;
  azimuth_deg?: number;
  suggestions?: DeviceSuggestion[];
}

export interface Reaction {
  node_label: number;
  pu_kn: number;
  tu_kn: number;
  vu_kn: number;
}

export interface WindSummary {
  wind_speed_ms: number;
  wind_speed_kmh: number;
  exposure: "B" | "C" | "D";
  struct_class: number;
  i_factor: number;
  kzt: number;
  kd: number;
  height_m: number;
  kz_top: number;
  qz_top_pa: number;
  gh: number;
  total_dev_wind_kn: number;
  total_dev_dead_kn: number;
}

export interface DeviceLoadRow {
  status: string;
  tenant: string;
  device_name: string;
  elev_z_m: number;
  qty: number;
  qz_pa: number;
  epa_total_m2: number;
  fw_kn: number;
  fw_factored_kn: number;
  fd_factored_kn: number;
}

export interface MemberCheckRow {
  sec_name: string;
  member_count?: number;
  ag_mm2: number;
  b_mm: number;
  t_mm: number;
  r_min_mm: number;
  length_mm: number;
  l_over_r: number;
  kl_over_r: number;
  q_factor: number;
  fe_mpa: number;
  fcr_mpa: number;
  phi_pn_kn: number;
  pu_kn: number;
  stress_ratio: number;
  status: "AMAN" | "OVERSTRESS" | string;
  pu_opensees_kn?: number;
  phi_pn_opensees_kn?: number;
  sr_opensees?: number;
  status_opensees?: string;
  pu_mst_kn?: number;
  phi_pn_mst_kn?: number;
  sr_mst?: number;
  status_mst?: string;
  diff_sr?: number;
  accuracy_pct?: number;
  status_match?: boolean;
}

export interface MemberComparisonRow {
  pnl: number;
  members: string;
  typ: string;
  size: string;
  kl_r: number;
  pu_opensees_kn: number;
  phi_pn_opensees_kn: number;
  sr_opensees: number;
  status_opensees: string;
  pu_mst_kn: number;
  phi_pn_mst_kn: number;
  sr_mst: number;
  status_mst: string;
  diff_sr: number;
  accuracy_pct: number;
  status_match: boolean;
}

export interface AnchorBaseplateCheck {
  n_bolts: number;
  d_bolt_mm: number;
  fu_bolt_mpa: number;
  an_mm2: number;
  pu_bolt_kn: number;
  vu_bolt_kn: number;
  anchor_ratio: number;
  anchor_status: "AMAN" | "OVERSTRESS";
  bp_width_mm: number;
  bp_thick_mm: number;
  fp_mpa: number;
  fp_allow_mpa: number;
  m_mm: number;
  t_comp_mm: number;
  t_tens_mm: number;
  bp_ratio: number;
  bp_status: "AMAN" | "OVERSTRESS";
}

export interface FoundationCheck {
  fz_kn: number;
  moment_knm: number;
  wc_kn: number;
  ws_kn: number;
  raft_b_m: number;
  qc_kg_cm2: number;
  df_m: number;
  p_total_kn: number;
  q_max_kn_m2: number;
  q_allow_kn_m2: number;
  sf_bearing: number;
  sf_bearing_ok: boolean;
  sf_overturning: number;
  sf_overturning_ok: boolean;
}

export interface Member3DStress {
  id: number;
  x1: number;
  y1: number;
  z1: number;
  x2: number;
  y2: number;
  z2: number;
  sec_name: string;
  typ: string;
  pnl: number;
  pu_kn: number;
  phi_pn_kn: number;
  kl_over_r: number;
  stress_ratio: number;
}

export interface MstComparisonRow {
  category?: "SR" | "TWIST_SWAY_DISP" | "SUPPORT_REACTION";
  parameter: string;
  unit: string;
  webapps_val: number;
  mstower_val: number;
  accuracy_pct: number;
  note: string;
}

export interface TwistSwaySummary {
  operational_wind_kmh: number;
  sway_deg: number;
  mst_sway_deg: number;
  twist_deg: number;
  mst_twist_deg: number;
  disp_h_mm: number;
  mst_disp_h_mm: number;
  disp_z_mm: number;
  mst_disp_z_mm: number;
  sway_limit_deg: number;
  status: string;
}

export interface PreflightMissingDevice {
  id: number;
  kind: "DEVICE";
  name: string;
  tenant: string;
  status: string;
  elev_z_m: number;
  qty: number;
  suggestions: DeviceSuggestion[];
}

export interface PreflightMissingLinear {
  kind: "LINEAR";
  tag: string;
  name: string;
  zb_m: number;
  zt_m: number;
  qty: number;
  suggested_lib: string;
  note: string;
}

export interface PreflightMissingSection {
  kind: "MEMBER_SECTION";
  sec_id: number;
  name: string;
  suggested_lib: string;
}

export interface PreflightResult {
  site_name: string;
  default_vb_ms: number;
  default_exposure: "B" | "C" | "D";
  z_base_m: number;
  has_missing_references: boolean;
  missing_devices: PreflightMissingDevice[];
  missing_linear: PreflightMissingLinear[];
  missing_sections: PreflightMissingSection[];
}

export interface EngineeringReport {
  wind_summary: WindSummary & { z_base_m?: number };
  twist_sway_disp?: TwistSwaySummary;
  device_loads: DeviceLoadRow[];
  member_checks: MemberCheckRow[];
  member_comparison_rows?: MemberComparisonRow[];
  member_3d_stress?: Member3DStress[];
  mst_comparison?: MstComparisonRow[];
  anchor_baseplate: AnchorBaseplateCheck;
  foundation: FoundationCheck;
  recommendation: string;
}

export interface AnalysisParams {
  wind_speed_ms: number;
  exposure?: "B" | "C" | "D";
  struct_class?: 1 | 2 | 3;
  kzt?: number;
}

export interface AnalysisResult {
  run_id: number;
  site_name: string;
  wind_speed_ms: number;
  created_at: string;
  max_pu_kn: number;
  max_tu_kn: number;
  max_vu_kn: number;
  reactions: Reaction[];
  warnings: string[];
  engineering?: EngineeringReport;
}

export interface MsTowerReportResult {
  site_name: string;
  run_id: number;
  created_at: string;
  wind_speed_ms: number;
  scale: number;
  has_rpt: boolean;
  header: {
    program: string;
    job: string;
    title: string[];
    date: string;
  };
  member_rows_count: number;
  reaction_cases_count: number;
  rotation_points_count: number;
  ancillary_count: number;
  displacement_cases_count: number;
  mass_total_kg: number;
  report_text: string;
}
