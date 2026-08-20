def _log_bulk_summary(
    self,
    operation: str,
    reference_set_name: str,
    results: list[dict[str, Any]],
) -> None:

    self.logger.info(
        "========== BULK SUMMARY =========="
    )

    self.logger.info(
        "Reference Set: %s",
        reference_set_name,
    )

    self.logger.info(
        "Operation: %s",
        operation,
    )

    self.logger.info(
        "Total items: %d",
        len(results),
    )

    for item in results:

        ip = item.get(
            "ip",
            "-"
        )

        status = item.get(
            "status",
            "-"
        )

        if status == "failed":

            result_text = (
                f"FAILED: "
                f"{item.get('error', 'unknown error')}"
            )

        elif operation == "CHECK":

            exists = item.get(
                "exists",
                False
            )

            result_text = (
                "FOUND"
                if exists
                else "NOT_FOUND"
            )

        else:

            result_text = status.upper()

        self.logger.info(
            "IP=%s | OPERATION=%s | RESULT=%s",
            ip,
            operation,
            result_text,
        )

    self.logger.info(
        "========== END SUMMARY =========="
    )
