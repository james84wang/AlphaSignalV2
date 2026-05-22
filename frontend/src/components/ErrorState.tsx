interface Props {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="rounded-xl bg-red-950/60 border border-red-800 px-6 py-5 max-w-md">
        <p className="text-red-400 font-semibold mb-1">Error</p>
        <p className="text-slate-400 text-sm">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 text-sm text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
