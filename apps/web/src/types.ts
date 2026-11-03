export type TopicStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

export interface Topic {
  id: string;
  title: string;
  description: string;
  priority: number;
  status: TopicStatus;
  target_platforms: string[];
  keywords: string[];
  planned_date: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface Content {
  id: string;
  title: string;
  body: string;
  content_type: string;
  status: string;
  topic_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublishTask {
  id: string;
  content_id: string;
  platform: string;
  account_id: string;
  status: string;
  scheduled_at: string | null;
  published_at: string | null;
  external_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceHit {
  rule_id: string;
  rule_name: string;
  severity: string;
  keyword: string;
  source: string;
  position: number;
}

export interface ComplianceReport {
  passed: boolean;
  blocking: ComplianceHit[];
  warnings: ComplianceHit[];
  summary: string;
}

export interface DraftResponse {
  title: string;
  title_candidates: string[];
  title_candidates_detailed?: {
    title: string;
    mechanism: string;
    mechanism_name: string;
    note: string;
  }[];
  body: string;
  hashtags: string[];
  platform: string;
  title_limit: number;
  body_limit: number;
  source?: string;
}

export interface ValidationResult {
  passed: boolean;
  blocking: string[];
  platform_errors: string[];
  sop_warnings: string[];
  compliance_passed: boolean;
  compliance_summary: string;
  keyword_coverage: Record<string, boolean>;
}

export interface HotNote {
  title: string;
  platform: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  engagement: number;
  author_fans: number | null;
  url: string;
  category: string;
  published_at: string;
  source: string;
}

export interface HotNoteListResponse {
  platform: string;
  provider: string;
  keyword: string | null;
  total: number;
  notes: HotNote[];
}

export interface TrendImportResponse {
  imported: number;
  skipped_duplicates: number;
  provider: string;
  topics: { id: string; title: string }[];
}

export interface PlatformBreakdown {
  views: number;
  likes: number;
  comments: number;
  shares: number;
  followers_gained: number;
  followers_lost: number;
  engagement_rate: number;
  count: number;
}

export interface MetricsSummaryStats {
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  total_followers_gained: number;
  avg_engagement_rate: number;
}

export interface ContentPerformance {
  content_id: string;
  title: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  interactions: number;
  engagement_rate: number;
}

export interface RetrospectiveResponse {
  days: number;
  start_date: string;
  end_date: string;
  period: MetricsSummaryStats;
  previous_period: MetricsSummaryStats;
  top_contents: ContentPerformance[];
  source_counts: Record<string, number>;
}

export interface CalendarEntry {
  id: string;
  title: string;
  status: string;
  priority: number;
  target_platforms: string[];
}

export interface CalendarDay {
  planned_date: string;
  count: number;
  topics: CalendarEntry[];
}

export interface PlatformAccount {
  id: string;
  platform: string;
  display_name: string;
  status: string;
}

export interface MetricsSummary {
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  total_followers_gained: number;
  avg_engagement_rate: number;
}
