export interface SetupStatus {
  initialized: boolean;
  needs_admin_setup: boolean;
}

export interface SetupIssue {
  code: string;
  message: string;
  field?: string | null;
}

export interface SetupCheck {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
}

export interface SetupPreflightResult {
  valid: boolean;
  errors: SetupIssue[];
  warnings: SetupIssue[];
  checks: SetupCheck[];
}

export interface SetupRequest {
  domain: string;
  acme_email: string;
  enable_https: boolean;
  use_staging_acme: boolean;
  cors_origins: string[];
}

export interface SetupInitializeResult {
  status: string;
  message: string;
  preflight: SetupPreflightResult;
}
