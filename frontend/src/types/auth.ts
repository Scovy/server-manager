export interface AuthUser {
  id: number;
  username: string;
  role: string;
  two_factor_enabled: boolean;
}

export interface AuthSuccessResponse {
  status: 'ok';
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: AuthUser;
  bootstrap_created?: boolean;
}

export interface TwoFactorRequiredResponse {
  status: '2fa_required';
  message: string;
}

export type LoginResponse = AuthSuccessResponse | TwoFactorRequiredResponse;

export interface LoginRequest {
  username: string;
  password: string;
  totp_code?: string;
}

export interface InitialAdminCreateRequest {
  username: string;
  password: string;
}

export interface TwoFactorSetupResponse {
  secret: string;
  otpauth_uri: string;
}

export interface TwoFactorVerifyResponse {
  status: 'verified' | 'enabled';
  two_factor_enabled: boolean;
  access_token?: string;
  token_type?: 'bearer';
  expires_in?: number;
  user?: AuthUser;
}
