'''
Data Quality Monitor - CLI Entry Point
Usage:
    python main.py <filepath> # run with defaults
    python main.py <filepath> -c configs/custom.yaml  # run with config
    python main.py <filepath> --no-parallel # sequential execution
    python main.py --history # show run history
    python main.py --history -f sample.csv # history for one file
Works with ANY tabular data file: CSV, Excel (.xlsx/.xls), JSON
'''

import sys
import os
import argparse

from engine import QualityEngine
from report_generator import ReportGenerator


def main():
    parser = argparse.ArgumentParser(
        description="Data Quality Monitor Framework - Check any tabular data file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py sample.csv
  python main.py data.xlsx -c configs/customer_data.yaml
  python main.py users.json --no-parallel
  python main.py --history
  python main.py --history -f sample.csv
        """,
    )

    parser.add_argument("filepath", nargs="?", help="Path to data file (CSV, Excel, JSON)")
    parser.add_argument("-c", "--config", help="Path to YAML config file", default=None)
    parser.add_argument("--no-parallel", action="store_true", help="Run checks sequentially")
    parser.add_argument("--save-report", action="store_true", help="Save report to reports/ folder")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show sample flagged records in report")
    parser.add_argument("--export-csv", action="store_true", help="Export flagged records to CSV")
    parser.add_argument("--history", action="store_true", help="Show run history")
    parser.add_argument("-f", "--file-filter", help="Filter history by file name")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel workers (default: 4)")

    args = parser.parse_args()

    engine = QualityEngine(max_workers=args.workers)
    reporter = ReportGenerator()

    # History mode - show past runs and scores, optionally filtered by file name
    if args.history:
        runs = engine.get_history(file_name=args.file_filter)
        if not runs:
            print("No run history found.")
            return

        print(f"\n{'='*70}")
        print("RUN HISTORY")
        print(f"{'='*70}")
        print(f"{'ID':<5} {'File':<25} {'Score':<10} {'Grade':<20} {'Timestamp'}")
        print("-" * 70)
        for run in runs:
            print(
                f"{run['run_id']:<5} "
                f"{run['file_name']:<25} "
                f"{run['overall_score']:<10.2f} "
                f"{run['grade']:<20} "
                f"{run['run_timestamp']}"
            )
        print()
        return

    # Quality check mode - run checks on the provided file
    if not args.filepath:
        parser.print_help()
        print("\nError: filepath is required (unless using --history)")
        sys.exit(1)

    if not os.path.exists(args.filepath):
        print(f"Error: File '{args.filepath}' not found")
        sys.exit(1)

    # main (run engine)
    report = engine.run(
        filepath=args.filepath,
        config_path=args.config,
        parallel=not args.no_parallel,
    )

    # print report
    reporter.print_report(report, verbose=args.verbose)

    # optionally save
    if args.save_report:
        path = reporter.save_report(report, verbose=args.verbose)
        print(f"\nReport saved to: {path}")

    # optionally export flagged records
    if args.export_csv:
        csv_path = engine.export_flagged_csv(report)
        if csv_path:
            print(f"Flagged records exported to: {csv_path}")


if __name__ == "__main__":
    main()