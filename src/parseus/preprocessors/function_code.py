"""
Contains operations for analyzing a list of function codes from Elasticsearch documents.
"""


def fc_transformer(agg_results):
    dictionary_list = []
    timestamp = agg_results["key"]["date"]
    src_ip = agg_results["key"]["source_ips"]
    dest_ip = agg_results["key"]["destination_ips"]
    for func_code in agg_results["func_codes"]["buckets"]:
        row = {"@timestamp": timestamp}
        code = func_code["key"]
        count = func_code["doc_count"]
        row["source_ip"] = src_ip
        row["dest_ip"] = dest_ip
        row["code"] = code
        row["count"] = count
        dictionary_list.append(row)
    return dictionary_list


def format_code_count_string(codes: list, counts: list):
    # Find the maximum length of the strings and the string representation of integers
    max_code_length = max(len(c) for c in codes)
    max_count_length = max(len(str(x)) for x in counts)

    # Create the formatted string
    formatted_lines = []
    for s, i in zip(codes, counts):
        # Justify the codes to the left and the counts to the right
        line = f"{i:>{max_count_length}}  {s:<{max_code_length}}"
        formatted_lines.append(line)

    result = "\n".join(formatted_lines)
    return result


def get_summary_from_function_codes(fc_state):
    start_time = fc_state.first_valid_index()
    start_time_str = start_time.strftime("%B %d, %Y %H:%M:%S")
    end_time = fc_state.last_valid_index()
    end_time_str = end_time.strftime("%B %d, %Y %H:%M:%S")
    total_time = end_time - start_time
    summary = {}
    summary["start_time"] = start_time_str
    summary["end_time"] = end_time_str
    summary["start_end"] = f"{start_time_str} to {end_time_str}"
    summary["total_time"] = str(total_time)
    summary["unique_timestamps"] = len(fc_state.index.drop_duplicates())
    summary["unique_pairs"] = len(fc_state[["source_ip", "dest_ip"]].drop_duplicates())
    fc_counts = (
        fc_state[["count", "code"]]
        .groupby("code", as_index=False)["count"]
        .sum()
        .sort_values(by="count", ascending=False)
    )
    if not fc_counts.empty:
        annotation_summary = format_code_count_string(
            fc_counts["code"].to_list(), fc_counts["count"].to_list()
        )
    else:
        annotation_summary = ""
    summary["fc_summary"] = annotation_summary
    return summary


def get_function_codes_data(fc_state):
    conversations = {}
    for (src, dest), grouped_df in fc_state.groupby(["source_ip", "dest_ip"]):
        results_dict = {}
        src_dest = f"{src} -> {dest}"
        conversations[src_dest] = {}
        conversations[src_dest]["stats"] = get_summary_from_function_codes(grouped_df)
        conversations[src_dest]["protocols"] = ["modbus"]
        for index, row in grouped_df.iterrows():
            timestamp = index.strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # Format the timestamp
            code = row["code"]
            count = row["count"]
            if timestamp not in results_dict:
                results_dict[timestamp] = {}
            results_dict[timestamp][code] = count
        conversations[src_dest]["points"] = results_dict

    return conversations
