export interface BackupItem {
  filename: string;
  size_bytes: number;
  updated_at: string;
}

export interface BackupRestoreResult {
  status: string;
  message: string;
  restored: {
    database: boolean;
    apps_dir: boolean;
    config_files: string[];
  };
}
