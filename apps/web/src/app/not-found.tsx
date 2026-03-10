export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-base)]">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-[var(--text-primary)]">404</h1>
        <p className="mt-2 text-[var(--text-secondary)]">Page not found</p>
        <a
          href="/"
          className="mt-4 inline-block text-[var(--color-brand-primary)] hover:underline"
        >
          Go back home
        </a>
      </div>
    </div>
  );
}
