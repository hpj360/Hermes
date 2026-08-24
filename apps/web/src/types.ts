export type TopicStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

export interface Topic {
  id: string;
  title: string;
  description: string;
  priority: number;
  status: TopicStatus;
  target_platforms: string[];
  keywords: string[];
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
