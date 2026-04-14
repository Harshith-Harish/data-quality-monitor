#Formats quality reports for console and file output.

import os
from datetime import datetime


class ReportGenerator:
    # Formats the raw results from the engine into a human-readable report.
    # Can print to console or save to a text file. Designed for easy reading by data

    def print_report(self, report: dict, verbose: bool = False):
        """Print a formatted report to the console. Verbose mode includes sample flagged records."""
        text = self.format_report(report, verbose=verbose)
        print(text)

    def save_report(self, report: dict, output_dir: str = "reports", verbose: bool = False) -> str:
        """Save report to a text file. Returns the file path."""
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"quality_report_{report['file_name']}_{timestamp}.txt"
        filepath = os.path.join(output_dir, filename)

        text = self.format_report(report, verbose=verbose)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)

        return filepath

    def format_report(self, report: dict, verbose: bool = False) -> str:
        # Turns report dicts into readable text.
        lines = []
        sep = "=" * 60
        dash = "-" * 60

        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        # Header 
        lines.append(sep)
        lines.append("DATA QUALITY REPORT")
        lines.append(sep)
        lines.append(f"File:          {report['file_name']}")
        lines.append(f"Data Source:   {report['data_source']}")
        lines.append(f"Timestamp:     {report['timestamp']}")
        lines.append(f"Rows:          {report['rows']:,}")
        lines.append(f"Columns:       {report['columns']}")
        lines.append(f"Primary Key:   {report.get('primary_key', 'None (using row index)')}")
        lines.append(f"Checks Run:    {report['checks_run']}")
        lines.append(f"Execution:     {report['execution_time_sec']}s (parallel={report['parallel']})")
        lines.append(f"Run ID:        {report['run_id']}")
        lines.append("")

        # Data Preview 
        if report.get("preview"):
            lines.append(dash)
            lines.append("DATA PREVIEW (first 5 rows)")
            lines.append(dash)
            for i, row in enumerate(report["preview"][:5]):
                lines.append(f"  Row {i}: {row}")
            lines.append("")

        # Sort results by severity (critical first) 
        sorted_results = sorted(
            report["results"],
            key=lambda r: (r["passed"], SEVERITY_ORDER.get(r["severity"], 99))
        )

        #Individual Check Results
        for r in sorted_results:
            status = "PASS" if r["passed"] else "FAIL"
            lines.append(dash)
            lines.append(f"[{status}] {r['check_name'].upper()} ({r['category']} | {r['severity']})")
            lines.append(dash)

            if r["issue_count"] > 0:
                lines.append(f"Issues: {r['issue_count']} / {r['total_checked']} ({r['issue_pct']}%)")
                lines.append(f"Action: {r.get('action_type', 'review')}")

            for detail in r["details"]:
                lines.append(f"  {detail}")

            # show recommendation if present
            if r.get("recommendation"):
                lines.append(f"  >> {r['recommendation']}")

            # verbose mode: show sample flagged records
            if verbose and r.get("flagged_count", 0) > 0:
                lines.append(f"  Flagged records (showing up to 5 of {r['flagged_count']}):")
                # find flagged records for this check
                check_flags = [
                    f for f in report.get("flagged_records", [])
                    if f["check"] == r["check_name"]
                ]
                for f in check_flags[:5]:
                    pk_str = ", ".join(f"{k}: {v}" for k, v in f["primary_key"].items())
                    dev_str = f" (deviation: {f['deviation']}σ)" if f.get("deviation") else ""
                    lines.append(f"    → Row {f['row_index']} ({pk_str}) | {f['column']} = {f['value']} | expected: {f['expected']}{dev_str}")

            lines.append("")

        #Recommendations Summary
        recs = [(r["check_name"], r["severity"], r["recommendation"])
                for r in sorted_results if r.get("recommendation")]
        if recs:
            lines.append(sep)
            lines.append("RECOMMENDATIONS (by priority)")
            lines.append(sep)
            for name, sev, rec in recs:
                lines.append(f"  [{sev.upper()}] {name}: {rec}")
            lines.append("")

        #KPI Summary
        kpi = report["kpi"]
        lines.append(sep)
        lines.append("DATA QUALITY KPI SUMMARY")
        lines.append(sep)

        for dim, score in kpi["dimensions"].items():
            lines.append(f"  {dim.replace('_', ' ').title():20s} {score:.2f}%")

        lines.append("")
        lines.append(f"  OVERALL SCORE:       {kpi['overall_score']:.2f}%")
        lines.append(f"  GRADE:               {kpi['grade']}")
        lines.append(f"  TOTAL ISSUES:        {kpi['total_issues']}")
        flagged_count = len(report.get("flagged_records", []))
        lines.append(f"  FLAGGED RECORDS:     {flagged_count}")
        lines.append(sep)

        return "\n".join(lines)