import type { SentimentTimelineEntry } from "../types";

/**
 * Sentiment trend as a plain SVG — no charting dependency (gap P12).
 *
 * Two things this deliberately does not do. It does not zero-fill missing days:
 * the API omits days with no activity, and inventing a flat line for them would
 * draw a trend that never happened, so a gap stays a gap. And it does not treat
 * `avg_score` as a percentage of positivity — it is the mean of the per-message
 * score, so the axis is labelled as a mean rather than as a share.
 *
 * The chart is decorative: every number it shows is also in the table beneath it,
 * so a screen reader and a sighted reader get the same data. That is also what
 * keeps the axe audit happy — an `img` with no text alternative would fail.
 */

const WIDTH = 560;
const HEIGHT = 160;
const PADDING = { top: 12, right: 12, bottom: 24, left: 40 };

const PLOT_WIDTH = WIDTH - PADDING.left - PADDING.right;
const PLOT_HEIGHT = HEIGHT - PADDING.top - PADDING.bottom;

function dayLabel(iso: string): string {
  // `YYYY-MM-DD` is already the day we want; reformatting through a Date would
  // shift it by a timezone and mislabel the axis.
  return iso.slice(5);
}

export default function SentimentChart({
  entries,
}: {
  entries: SentimentTimelineEntry[];
}) {
  if (entries.length === 0) return null;

  // One slot per day *in the window*, so a day with no messages leaves a real gap
  // at the right position rather than compressing the axis to hide it.
  const peak = Math.max(...entries.map((e) => e.messages), 1);
  const slot = PLOT_WIDTH / Math.max(entries.length, 1);
  const barWidth = Math.max(Math.min(slot * 0.6, 28), 2);

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full h-auto"
      role="img"
      aria-label={`Sentiment trend across ${entries.length} active days. The table below lists the same figures.`}
    >
      {/* Volume axis: two gridlines and their labels, enough to read a bar
          height without turning the chart into a grid. */}
      {[0, 0.5, 1].map((fraction) => {
        const y = PADDING.top + PLOT_HEIGHT * (1 - fraction);
        return (
          <g key={fraction}>
            <line
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={y}
              y2={y}
              className="stroke-gray-200"
              strokeWidth={1}
            />
            <text
              x={PADDING.left - 6}
              y={y + 3}
              textAnchor="end"
              className="fill-gray-500 text-[9px]"
            >
              {Math.round(peak * fraction)}
            </text>
          </g>
        );
      })}

      {entries.map((entry, index) => {
        const height = (entry.messages / peak) * PLOT_HEIGHT;
        const x = PADDING.left + index * slot + (slot - barWidth) / 2;
        const y = PADDING.top + PLOT_HEIGHT - height;
        return (
          <rect
            key={entry.date}
            x={x}
            y={y}
            width={barWidth}
            height={height}
            rx={2}
            className="fill-green-600"
          >
            <title>{`${entry.date}: ${entry.messages} messages, mean score ${entry.avg_score.toFixed(2)}`}</title>
          </rect>
        );
      })}

      {/* First, middle and last only — a 30-day axis with 30 labels is
          unreadable at this width. */}
      {[0, Math.floor(entries.length / 2), entries.length - 1]
        .filter((index, position, all) => all.indexOf(index) === position)
        .map((index) => (
          <text
            key={entries[index].date}
            x={PADDING.left + index * slot + slot / 2}
            y={HEIGHT - 8}
            textAnchor="middle"
            className="fill-gray-500 text-[9px]"
          >
            {dayLabel(entries[index].date)}
          </text>
        ))}
    </svg>
  );
}
