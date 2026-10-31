#!/usr/bin/env python3
"""
Creates a Frame that tells what devices have updated at a given time step.
"""

import logging

import numpy as np
import pandas as pd


def make_reg_updates_df(binned_regstate):
    """
    Creates a frame of device updates
    """
    diff_frame = binned_regstate.diff()
    diff_frame = diff_frame.drop(diff_frame.index[0])
    reg_updates_df = replace_ints_with_bits(diff_frame)
    return reg_updates_df


def replace_ints_with_bits(original_df):
    """
    Replaces rows with numbers with a 1 if a value is present.
    """
    new_df = pd.DataFrame(index=original_df.index)
    for col_name in original_df.columns:
        selected_col = original_df[col_name]
        new_df[col_name] = np.where(selected_col != 0, 1, 0)
    return new_df


def get_title(reg_updates_df):
    """
    Determines the correct title from the number of devices that are passed.
    """
    devices = set()
    for column in reg_updates_df.columns:
        if "->" in column:
            devices.add(column.split(":")[0])
    if len(devices) > 1:
        title = "Multiple Devices"
    else:
        title = devices.pop()
    return title


def parse_reg_names(reg_name, verbose=False):
    """
    Takes a column name from reg_ops and extracts info
    """
    reg_info = {"con": reg_name}
    src_dst = reg_name.split("->")
    reg_info["src"] = src_dst[0]
    reg_info["dst"] = src_dst[1].split(":")[0]
    reg_info["reg_designation"] = parse_reg_designation(src_dst[1])
    if reg_info["reg_designation"]:
        reg_info["reg"] = src_dst[1].split("_")[-1]
    else:
        reg_info["reg_designation"] = "none"
        reg_info["reg"] = src_dst[1].split(":")[-1]
    if verbose:
        for key, value in reg_info.items():
            logging.debug(f"{key}: {value}")
    return reg_info


def map_all_reg_designations(reg_state_df):
    """
    gets all register designations from a reg_state_df
    """
    reg_designations = set()
    counter = 1
    for column in reg_state_df.columns:
        reg_info = parse_reg_names(column)
        reg_designations.add(reg_info["reg_designation"])
    reg_designation_lookup = {}
    for reg_designation in reg_designations:
        reg_designation_lookup[reg_designation] = counter
        counter += 1
    return reg_designation_lookup


def parse_reg_designation(reg_designation):
    """
    strips out the end digit from the reg_designatiation
    example: input: point_Analog_Input__16Bit_with_Flag_0
    output:  point_Analog_Input__16Bit_with_Flag
    """
    designation = reg_designation.split(":")[1].split("_")
    parsed_designation = "_".join(designation[0:-1])
    return parsed_designation


def map_ip_pairs(reg_state_df):
    """
    Maps a conversation of IPs to a short name.
    Example: Input: 10.2.2.2->10.2.2.1
             Output: {10.2.2.2->10.2.2.1:1,}
    """
    ip_pairs_lookup = {}
    ip_pairs = set()
    counter = 1
    for column in reg_state_df.columns:
        reg_info = parse_reg_names(column)
        key = f"{reg_info['src']}->{reg_info['dst']}"
        ip_pairs.add(key)
    for ip_pair in ip_pairs:
        ip_pairs_lookup[ip_pair] = counter
        counter += 1
    return ip_pairs_lookup


def map_shortname_to_canonical(reg_state_df):
    """
    Constructs short names for a given reg_state data frame and
    returns a mapping of the short name to the cononcical reg_name
    Example: '10:10:0': '10.2.3.53->10.2.3.20:point_Counter__16Bit_without_Flag_0'
    """
    ip_pairs_lookup = map_ip_pairs(reg_state_df)
    reg_des_lookup = map_all_reg_designations(reg_state_df)
    short_to_con = {}
    for column in reg_state_df.columns:
        reg_info = parse_reg_names(column)
        src_dst_key = f"{reg_info['src']}->{reg_info['dst']}"
        # Find the shortned name each of the lookups
        src_dst = ip_pairs_lookup[src_dst_key]
        reg_des = reg_des_lookup[reg_info["reg_designation"]]
        register = reg_info["reg"]
        short_name = f"{src_dst}:{reg_des}:{register}"
        short_to_con[short_name] = reg_info["con"]
    return short_to_con
