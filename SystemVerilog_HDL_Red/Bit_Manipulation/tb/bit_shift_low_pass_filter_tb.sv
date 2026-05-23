`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_run_bslpf_tb.do
*/

module bit_shift_low_pass_filter_tb;

	// ------------------------------------------------------------------------
	// Clock: 50 MHz => 20 ns period
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 5.714;

	logic clock_175 = 1'b0;
	always #(TCLK_NS/2) clock_175 = ~clock_175;

	// ------------------------------------------------------------------------
	// Image parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM    = 128;
	parameter int unsigned IMAGE_DIM_BS = 7;

	// ------------------------------------------------------------------------
	// Input stream paths
	// This testbench now targets the FINAL low-pass filter, so its inputs are
	// the fused output stream, not raw RGB pixels.
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/bslpf/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/bslpf/output_data";

	localparam string IN_VALID_MIF = {IN_DIR, "/SIM_PIXEL_VALID_IN.mif"};
	localparam string IN_SOLF_MIF  = {IN_DIR, "/SIM_SOLF_IN.mif"};
	localparam string IN_EOLF_MIF  = {IN_DIR, "/SIM_EOLF_IN.mif"};
	localparam string IN_ROW_MIF   = {IN_DIR, "/SIM_ROW_IDX_IN.mif"};
	localparam string IN_COL_MIF   = {IN_DIR, "/SIM_COLUMN_IDX_IN.mif"};
	localparam string IN_CONF_MIF  = {IN_DIR, "/SIM_CONFIDENCE_PIXEL_BIT_DATA_IN.mif"};
	localparam string IN_DISP_MIF  = {IN_DIR, "/SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA_IN.mif"};

	// ------------------------------------------------------------------------
	// Stream bounds
	// ------------------------------------------------------------------------
	localparam int MAX_DEPTH = 400000;
	int DEPTH = 0;

	localparam int WARMUP_CYCLES = 16;

	// ------------------------------------------------------------------------
	// Output capture length
	// 7x7 final filter has roughly 3 rows + 3 columns of centre delay, so use
	// a larger tail than the old pre-EPI BSLPF testbench.
	// ------------------------------------------------------------------------
	localparam int EXTRA_TAIL    = 2000;
	localparam int OUT_MAX_DEPTH = MAX_DEPTH + WARMUP_CYCLES + EXTRA_TAIL + 256;

	// ------------------------------------------------------------------------
	// Output MIF filenames
	// ------------------------------------------------------------------------
	localparam string OUT_VALID_MIF        = "SIM_PIXEL_VALID_OUT.mif";
	localparam string OUT_SOLF_MIF         = "SIM_SOLF_OUT.mif";
	localparam string OUT_EOLF_MIF         = "SIM_EOLF_OUT.mif";
	localparam string OUT_ROW_IDX_MIF      = "SIM_ROW_IDX_OUT.mif";
	localparam string OUT_COLUMN_IDX_MIF   = "SIM_COLUMN_IDX_OUT.mif";
	localparam string OUT_CONF_MIF         = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif";
	localparam string OUT_WEIGHTED_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif";

	// ------------------------------------------------------------------------
	// Stimulus memories
	// ------------------------------------------------------------------------
	logic                    valid_mem [0:MAX_DEPTH-1];
	logic                    solf_mem  [0:MAX_DEPTH-1];
	logic                    eolf_mem  [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] row_mem   [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] col_mem   [0:MAX_DEPTH-1];
	logic [9:0]             conf_mem  [0:MAX_DEPTH-1];
	logic signed [15:0]      disp_mem  [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Captured outputs
	// ------------------------------------------------------------------------
	logic                    out_valid_mem [0:OUT_MAX_DEPTH-1];
	logic                    out_solf_mem  [0:OUT_MAX_DEPTH-1];
	logic                    out_eolf_mem  [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_row_mem   [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_col_mem   [0:OUT_MAX_DEPTH-1];
	logic [9:0]             out_conf_mem  [0:OUT_MAX_DEPTH-1];
	logic signed [15:0]      out_disp_mem  [0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic                    pixel_valid_in = 1'b0;
	logic                    solf_in        = 1'b0;
	logic                    eolf_in        = 1'b0;
	logic [IMAGE_DIM_BS-1:0] row_idx_in     = '0;
	logic [IMAGE_DIM_BS-1:0] column_idx_in  = '0;
	logic [9:0]             confidence_in  = 10'd0;
	logic signed [15:0]      disparity_in   = 16'sd0;

	// ------------------------------------------------------------------------
	// DUT outputs
	// ------------------------------------------------------------------------
	logic                    pixel_valid_out;
	logic                    solf_out;
	logic                    eolf_out;
	logic [IMAGE_DIM_BS-1:0] row_idx_out;
	logic [IMAGE_DIM_BS-1:0] column_idx_out;
	logic [9:0]             confidence_out;
	logic signed [15:0]      disparity_out;

	// ------------------------------------------------------------------------
	// DUT instance
	// ------------------------------------------------------------------------
	bit_shift_low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT (
		.clk(clock_175),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_valid_in(pixel_valid_in),
		.row_idx_in(row_idx_in),
		.column_idx_in(column_idx_in),
		.confidence_in(confidence_in),
		.disparity_in(disparity_in),

		.solf_out(solf_out),
		.eolf_out(eolf_out),
		.pixel_valid_out(pixel_valid_out),
		.row_idx_out(row_idx_out),
		.column_idx_out(column_idx_out),
		.confidence_out(confidence_out),
		.disparity_out(disparity_out)
	);

	// ------------------------------------------------------------------------
	// Helper: parse DEPTH=... from MIF header
	// ------------------------------------------------------------------------
	function automatic int read_depth_from_mif(string mif_path);
		int fd;
		string line;
		int d;
		int rc;

		d  = -1;
		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF to read depth: %s", mif_path);
		end

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			rc = $sscanf(line, "DEPTH=%d;", d);
			if (rc == 1) begin
				$fclose(fd);
				return d;
			end
		end

		$fclose(fd);
		$fatal(1, "ERROR: Could not find DEPTH=... in MIF header: %s", mif_path);
		return -1;
	endfunction

	// ------------------------------------------------------------------------
	// Load MIF helpers
	// ------------------------------------------------------------------------
	task automatic load_mif_1(
		input string mif_path,
		input int depth,
		output logic mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 1'b0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 1'b0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	task automatic load_mif_7(
		input string mif_path,
		input int depth,
		output logic [IMAGE_DIM_BS-1:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [IMAGE_DIM_BS-1:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = '0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = '0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	task automatic load_mif_10(
		input string mif_path,
		input int depth,
		output logic [9:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [9:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 10'd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 10'd0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	task automatic load_mif_16_signed(
		input string mif_path,
		input int depth,
		output logic signed [15:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic signed [15:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 16'sd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 16'sd0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write output MIFs
	// ------------------------------------------------------------------------
	task automatic write_mif_1(
		input string mif_path,
		input int depth,
		input logic mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=1;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %0b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	task automatic write_mif_7(
		input string mif_path,
		input int depth,
		input logic [IMAGE_DIM_BS-1:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=%0d;", IMAGE_DIM_BS);
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %07b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	task automatic write_mif_10(
		input string mif_path,
		input int depth,
		input logic [9:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=10;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %015b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	task automatic write_mif_16(
		input string mif_path,
		input int depth,
		input logic signed [15:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=16;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %024b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Main sim
	// ------------------------------------------------------------------------
	int i;
	int out_idx;
	int OUT_DEPTH;

	initial begin
		$dumpfile("dump_bslpf.vcd");
		$dumpvars(0, bit_shift_low_pass_filter_tb);

		DEPTH = read_depth_from_mif(IN_VALID_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d (bad).", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d. Increase MAX_DEPTH.", DEPTH, MAX_DEPTH);
		end

		if ((DEPTH + WARMUP_CYCLES + EXTRA_TAIL) > OUT_MAX_DEPTH) begin
			$fatal(
				1,
				"ERROR: OUT_MAX_DEPTH too small. Need %0d but OUT_MAX_DEPTH=%0d.",
				(DEPTH + WARMUP_CYCLES + EXTRA_TAIL),
				OUT_MAX_DEPTH
			);
		end

		$display("INFO: Loading final low-pass input MIFs from: %s", IN_DIR);

		load_mif_1        (IN_VALID_MIF, DEPTH, valid_mem);
		load_mif_1        (IN_SOLF_MIF,  DEPTH, solf_mem);
		load_mif_1        (IN_EOLF_MIF,  DEPTH, eolf_mem);
		load_mif_7        (IN_ROW_MIF,   DEPTH, row_mem);
		load_mif_7        (IN_COL_MIF,   DEPTH, col_mem);
		load_mif_10       (IN_CONF_MIF,  DEPTH, conf_mem);
		load_mif_16_signed(IN_DISP_MIF,  DEPTH, disp_mem);

		repeat (4) @(posedge clock_175);

		pixel_valid_in = 1'b0;
		solf_in        = 1'b0;
		eolf_in        = 1'b0;
		row_idx_in     = '0;
		column_idx_in  = '0;
		confidence_in  = 10'd0;
		disparity_in   = 16'sd0;

		for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
			out_valid_mem[k] = 1'b0;
			out_solf_mem[k]  = 1'b0;
			out_eolf_mem[k]  = 1'b0;
			out_row_mem[k]   = '0;
			out_col_mem[k]   = '0;
			out_conf_mem[k]  = 10'd0;
			out_disp_mem[k]  = 16'sd0;
		end

		repeat (4) @(posedge clock_175);

		out_idx   = 0;
		OUT_DEPTH = 0;

		// Warm-up
		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_175);

			pixel_valid_in <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;
			row_idx_in     <= '0;
			column_idx_in  <= '0;
			confidence_in  <= 10'd0;
			disparity_in   <= 16'sd0;

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;
			out_row_mem[out_idx]   <= row_idx_out;
			out_col_mem[out_idx]   <= column_idx_out;
			out_conf_mem[out_idx]  <= confidence_out;
			out_disp_mem[out_idx]  <= disparity_out;

			out_idx <= out_idx + 1;
		end

		// Stimulus
		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_175);

			pixel_valid_in <= valid_mem[i];
			solf_in        <= solf_mem[i];
			eolf_in        <= eolf_mem[i];
			row_idx_in     <= row_mem[i];
			column_idx_in  <= col_mem[i];
			confidence_in  <= conf_mem[i];
			disparity_in   <= disp_mem[i];

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;
			out_row_mem[out_idx]   <= row_idx_out;
			out_col_mem[out_idx]   <= column_idx_out;
			out_conf_mem[out_idx]  <= confidence_out;
			out_disp_mem[out_idx]  <= disparity_out;

			out_idx <= out_idx + 1;
		end

		// Tail drain
		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_175);

			pixel_valid_in <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;
			row_idx_in     <= '0;
			column_idx_in  <= '0;
			confidence_in  <= 10'd0;
			disparity_in   <= 16'sd0;

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;
			out_row_mem[out_idx]   <= row_idx_out;
			out_col_mem[out_idx]   <= column_idx_out;
			out_conf_mem[out_idx]  <= confidence_out;
			out_disp_mem[out_idx]  <= disparity_out;

			out_idx <= out_idx + 1;
		end

		OUT_DEPTH = out_idx;

		$display("INFO: Writing final low-pass output MIFs (OUT_DEPTH=%0d) to: %s", OUT_DEPTH, OUT_DIR);

		write_mif_1 ({OUT_DIR, "/", OUT_VALID_MIF},         OUT_DEPTH, out_valid_mem);
		write_mif_1 ({OUT_DIR, "/", OUT_SOLF_MIF},          OUT_DEPTH, out_solf_mem);
		write_mif_1 ({OUT_DIR, "/", OUT_EOLF_MIF},          OUT_DEPTH, out_eolf_mem);
		write_mif_7 ({OUT_DIR, "/", OUT_ROW_IDX_MIF},       OUT_DEPTH, out_row_mem);
		write_mif_7 ({OUT_DIR, "/", OUT_COLUMN_IDX_MIF},    OUT_DEPTH, out_col_mem);
		write_mif_10({OUT_DIR, "/", OUT_CONF_MIF},          OUT_DEPTH, out_conf_mem);
		write_mif_16({OUT_DIR, "/", OUT_WEIGHTED_DISP_MIF}, OUT_DEPTH, out_disp_mem);

		$display("INFO: Finished. VCD = dump_bslpf.vcd");
		$finish;
	end

endmodule