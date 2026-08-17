# FFXIV EXH/EXD and Dialogue Control Code Technical Specification

This document details the binary structures of Final Fantasy XIV's Excel Header (`.exh`) and Excel Data (`.exd`) files, and specifies the syntax layout and variable-length integer serialization of dialogue control codes.

---

## 1. Excel Header (`.exh`) Format Specification

The `.exh` file acts as the schema definition for a data sheet. It is serialized in **Big-Endian** byte order.

### 1.1 Header Structure (32 Bytes)

| Offset (Hex) | Offset (Dec) | Size (Bytes) | Data Type | Field Name | Description |
|:---|:---|:---|:---|:---|:---|
| `0x00` | 0 | 4 | `char[4]` | `magic` | File signature, always `'EXHF'` (`0x45 0x58 0x48 0x46`) |
| `0x04` | 4 | 2 | `uint16` | `version` | File format version, always `3` (`0x0003`) |
| `0x06` | 6 | 2 | `uint16` | `row_size` | Size of the fixed column data block per row in the `.exd` file |
| `0x08` | 8 | 2 | `uint16` | `column_count` | Number of columns in the schema |
| `0x0A` | 10 | 2 | `uint16` | `page_count` | Number of data pages (individual EXD files) |
| `0x0C` | 12 | 2 | `uint16` | `language_count` | Number of languages supported by the sheet |
| `0x0E` | 14 | 2 | `uint16` | `reserved1` | Unknown / Reserved, usually `0` |
| `0x10` | 16 | 1 | `uint8` | `row_type` | Representation type: `1` = Flat (default), `2` = Sub-rows |
| `0x11` | 17 | 1 | `uint8` | `depth` | Sheet depth / hierarchy marker (typically `0` or `1`) |
| `0x12` | 18 | 2 | `uint16` | `reserved2` | Unknown / Reserved, usually `0` |
| `0x14` | 20 | 4 | `uint32` | `row_count` | Total number of rows across all pages |
| `0x18` | 24 | 4 | `uint32` | `reserved3` | Unknown / Reserved, usually `0` |
| `0x1C` | 28 | 4 | `uint32` | `reserved4` | Unknown / Reserved, usually `0` |

### 1.2 Column Definition Table

Directly follows the 32-byte header. Contains `column_count` entries. Each entry is **4 bytes** in size:
- **`type`** (`uint16`, big-endian, 2 bytes): Specifies the data type of the column.
- **`offset`** (`uint16`, big-endian, 2 bytes): Specifies the byte offset of the column's data relative to the start of the row data block (excluding the 6-byte row header) inside the `.exd` file.

#### Column Types and Sizes:
- `0x0000` (String): 4-byte `uint32` offset pointing into the row's local string table.
- `0x0001` (Boolean): 1 byte.
- `0x0002` (Int8): 1 byte.
- `0x0003` (UInt8): 1 byte.
- `0x0004` (Int16): 2 bytes.
- `0x0005` (UInt16): 2 bytes.
- `0x0006` (Int32): 4 bytes.
- `0x0007` (UInt32): 4 bytes.
- `0x0009` (Float32): 4 bytes.
- `0x000B` (Int64): 8 bytes.
- `0x000C` (UInt64): 8 bytes.
- `0x0019` to `0x0038` (Bit-packed Booleans): Packed as bits into a shared byte at `offset`. The bit index is calculated as `type - 0x0019` (0 to 31).

### 1.3 Page Definition Table

Directly follows the Column Definition Table. Contains `page_count` entries. Each entry is **8 bytes** in size:
- **`start_row_id`** (`uint32`, big-endian, 4 bytes): The starting Row ID for this page range.
- **`row_count`** (`uint32`, big-endian, 4 bytes): The number of rows in this page range.

### 1.4 Language Definition Table

Directly follows the Page Definition Table. Contains `language_count` entries. Each entry is **2 bytes** in size:
- **`language_code`** (`uint8`, 1 byte): Language code code.
  - `0`: Invariant / Universal
  - `1`: Japanese (`ja`)
  - `2`: English (`en`)
  - `3`: German (`de`)
  - `4`: French (`fr`)
  - `5`: Chinese Simplified (`chs`)
  - `6`: Chinese Traditional (`cht`)
  - `7`: Korean (`ko`)
- **`padding`** (`uint8`, 1 byte): Reserved / Padding, usually `0`.

---

## 2. Excel Data (`.exd`) Format Specification

The `.exd` file stores the raw data rows. It is serialized in **Big-Endian** byte order.

### 2.1 File Header (32 Bytes)

| Offset (Hex) | Size (Bytes) | Data Type | Field Name | Description |
|:---|:---|:---|:---|:---|
| `0x00` | 4 | `char[4]` | `magic` | File signature, always `'EXDF'` (`0x45 0x58 0x44 0x46`) |
| `0x04` | 2 | `uint16` | `version` | Data format version, typically `2` (`0x0002`) |
| `0x06` | 2 | `uint16` | `reserved` | Typically `2` (`0x0002`) |
| `0x08` | 4 | `uint32` | `index_table_size` | Size in bytes of the Index (Offset) Table |
| `0x0C` | 4 | `uint32` | `data_table_size` | Size in bytes of the Row Data Block + String Table |
| `0x10` | 16 | `char[16]` | `padding` | Reserved / Padding, all zeroes |

### 2.2 Index Table (Offset Table)

Starts at offset `0x20` (32) and contains `index_table_size / 8` entries. Each entry is **8 bytes**:
- **`row_id`** (`uint32`, big-endian, 4 bytes): The unique ID of the row. Sorted in ascending order.
- **`offset`** (`uint32`, big-endian, 4 bytes): The absolute byte offset of the row data block from the start of the `.exd` file.

### 2.3 Row Data Block Layout

Each row begins at its respective `offset` in the file.

#### 2.3.1 Standard Flat Row (`depth = 1`)
- **Row Header (6 bytes)**:
  - **`data_size`** (`uint32`, big-endian, 4 bytes): The size of the row data following this header (Fixed Column Data + String Table) in bytes.
  - **`sub_row_count`** (`uint16`, big-endian, 2 bytes): Set to `1`.
- **Fixed Column Data** (`row_size` bytes from EXH).
- **String Table**: Contiguous null-terminated UTF-8 strings.
  - For a String column, its 4-byte `uint32` value inside the Fixed Column Data represents a `string_offset` relative to the end of the Fixed Column Data block.
  - $\text{Absolute Address} = \text{Row Offset} + 6 + \text{row\_size} + \text{string\_offset}$.

#### 2.3.2 Sub-row Row Layout (`depth = 2`)
- **Row Header (6 bytes)**:
  - **`data_size`** (`uint32`, big-endian, 4 bytes): Size of all sub-rows data.
  - **`sub_row_count`** (`uint16`, big-endian, 2 bytes): Number of sub-rows $S$.
- Then, $S$ contiguous sub-rows follow, each structured as:
  - **`sub_row_id`** (`uint16`, big-endian, 2 bytes).
  - **Fixed Column Data** (`row_size` bytes from EXH).
  - **String Table**: Null-terminated UTF-8 strings for this sub-row, where offsets are relative to the end of this sub-row's Fixed Column Data.

---

## 3. Dialogue Text Control Code Layout

FFXIV dialogues contain inline commands (such as formatting, variables, and conditions) wrapped in a specific binary envelope.

### 3.1 Control Code Envelope

Every control code follows this layout:
- **Start Byte**: `0x02` (STX - Start of Text)
- **Code Type**: `uint8` (Code indicating the command)
- **Payload Length**: Variable-length integer specifying the payload size in bytes.
- **Payload**: Variable parameters/expressions.
- **End Byte**: `0x03` (ETX - End of Text)

```
+------+-----------+-------------------------+--------------------+------+
| 0x02 | Code Type | Payload Length (varint) | Payload (variable) | 0x03 |
+------+-----------+-------------------------+--------------------+------+
```

### 3.2 Variable-Length Integer Serialization (Varint)

To prevent the null byte (`0x00`) from terminating strings inside control code payloads, FFXIV serializes integers using a custom prefix-based scheme:

- **Literal Mode (`byte < 0xF0`)**:
  - The value is encoded directly in a single byte as `value + 1`.
  - To decode: `value = byte - 1`.
  - Represents values in the range `0` to `238`.
- **Prefix Mode (`byte >= 0xF0`)**:
  - The byte acts as a marker indicating how many subsequent bytes contain the big-endian integer:
    - `0xF0`: Read next **1 byte** as value.
    - `0xF1`: Read next **2 bytes** as big-endian `uint16`.
    - `0xF2`: Read next **3 bytes** as big-endian 24-bit integer.
    - `0xF6` (or `0xFE`): Read next **4 bytes** as big-endian `uint32`.

### 3.3 Variable Masking / Unmasking Design

During translation, control codes must be preserved exactly.
1. **Extraction**: Identify control codes by scanning for `0x02` bytes, parsing the `Payload Length` to skip and verify the trailing `0x03` byte.
2. **Masking**: Extract the entire `0x02` to `0x03` block, register it in a placeholder map with a unique token (e.g. `{VAR_0}`), and replace it in the text.
3. **Recursive String Processing**: If a control code contains translatable string expressions (e.g., conditional choices prefix-encoded inside an `0x28` block), they should be recursively parsed and translated.
4. **Unmasking**: Replace placeholders back with the original bytes from the map during file injection.
