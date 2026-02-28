/**
 * AES-256-GCM token encryption helpers.
 * Used for encrypting OAuth tokens before storage.
 * In demo mode, encryption is skipped (tokens are stored as-is in localStorage).
 */

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

/**
 * Encrypt a token string using AES-256-GCM.
 * Returns base64-encoded string of iv:ciphertext:tag.
 */
export async function encryptToken(token: string): Promise<string> {
  if (isDemoMode || !process.env.INTEGRATION_ENCRYPTION_KEY) {
    // Demo mode: return token as-is (base64 encoded for consistency)
    return Buffer.from(token).toString("base64");
  }

  const key = Buffer.from(process.env.INTEGRATION_ENCRYPTION_KEY, "hex");
  const { createCipheriv, randomBytes } = await import("crypto");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);

  let encrypted = cipher.update(token, "utf8", "base64");
  encrypted += cipher.final("base64");
  const tag = cipher.getAuthTag();

  return `${iv.toString("base64")}:${encrypted}:${tag.toString("base64")}`;
}

/**
 * Decrypt a token string encrypted with AES-256-GCM.
 */
export async function decryptToken(encryptedToken: string): Promise<string> {
  if (isDemoMode || !process.env.INTEGRATION_ENCRYPTION_KEY) {
    // Demo mode: decode from base64
    return Buffer.from(encryptedToken, "base64").toString("utf8");
  }

  const parts = encryptedToken.split(":");
  if (parts.length !== 3) {
    throw new Error("Invalid encrypted token format");
  }

  const [ivB64, ciphertextB64, tagB64] = parts;
  const key = Buffer.from(process.env.INTEGRATION_ENCRYPTION_KEY, "hex");
  const { createDecipheriv } = await import("crypto");

  const iv = Buffer.from(ivB64, "base64");
  const tag = Buffer.from(tagB64, "base64");
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);

  let decrypted = decipher.update(ciphertextB64, "base64", "utf8");
  decrypted += decipher.final("utf8");

  return decrypted;
}
