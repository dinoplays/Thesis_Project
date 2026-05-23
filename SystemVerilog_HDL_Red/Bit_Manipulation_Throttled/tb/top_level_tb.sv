`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_Throttled_run_tl_tb.do
*/

module top_level_tb;

	// ------------------------------------------------------------------------
	// Clock
	// ------------------------------------------------------------------------
	localparam realtime TCLK_NS = 12.500;

	logic clock_80 = 1'b0;
	always #(TCLK_NS/2.0) clock_80 = ~clock_80;

	// ------------------------------------------------------------------------
	// Parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM    = 128;
	parameter int unsigned IMAGE_DIM_BS = 7;

	// ------------------------------------------------------------------------
	// Paths
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation_Throttled/tb/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation_Throttled/tb/output_data";

	localparam string IN_PIXEL_MIF = {IN_DIR, "/SIM_PIXEL_BIT_DATA.mif"};
	localparam string IN_VALID_MIF = {IN_DIR, "/SIM_PIXEL_VALID_IN.mif"};
	localparam string IN_SOC_MIF   = {IN_DIR, "/SIM_SOC_IN.mif"};
	localparam string IN_EOC_MIF   = {IN_DIR, "/SIM_EOC_IN.mif"};
	localparam string IN_SOLF_MIF  = {IN_DIR, "/SIM_SOLF_IN.mif"};
	localparam string IN_EOLF_MIF  = {IN_DIR, "/SIM_EOLF_IN.mif"};

	// ------------------------------------------------------------------------
	// Output filenames (same as fused_aligned_output_tb)
	// ------------------------------------------------------------------------
	localparam string OUT_SOLF_MIF          = "SIM_SOLF_OUT.mif";
	localparam string OUT_EOLF_MIF          = "SIM_EOLF_OUT.mif";
	localparam string OUT_PIXEL_VALID_MIF   = "SIM_PIXEL_VALID_OUT.mif";
	localparam string OUT_ROW_IDX_MIF       = "SIM_ROW_IDX_OUT.mif";
	localparam string OUT_COLUMN_IDX_MIF    = "SIM_COLUMN_IDX_OUT.mif";
	localparam string OUT_CONF_PIXEL_MIF    = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif";
	localparam string OUT_WEIGHTED_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif";

	// ------------------------------------------------------------------------
	// Depth / sizes
	// ------------------------------------------------------------------------
	localparam int MAX_DEPTH     = 350000;
	localparam int WARMUP_CYCLES = 16;

	// Full pipeline needs a long drain because EPI/confidence/disparity/FAO
	// continue producing outputs well after the final input pixel.
	localparam int EXTRA_TAIL    = 18500;
	localparam int OUT_MAX_DEPTH = 4 + WARMUP_CYCLES + MAX_DEPTH + EXTRA_TAIL + 256;

	int DEPTH = 0;

	// ------------------------------------------------------------------------
	// Input memories
	// ------------------------------------------------------------------------
	logic [23:0] pixel_mem [0:MAX_DEPTH-1];
	logic        valid_mem [0:MAX_DEPTH-1];
	logic        soc_mem   [0:MAX_DEPTH-1];
	logic        eoc_mem   [0:MAX_DEPTH-1];
	logic        solf_mem  [0:MAX_DEPTH-1];
	logic        eolf_mem  [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic [23:0] sim_pixel_bit_data = 24'd0;
	logic        pixel_valid_in     = 1'b0;
	logic        soc_in             = 1'b0;
	logic        eoc_in             = 1'b0;
	logic        solf_in            = 1'b0;
	logic        eolf_in            = 1'b0;

	// ------------------------------------------------------------------------
	// DUT outputs
	// ------------------------------------------------------------------------
	logic        solf_out;
	logic        eolf_out;
	logic [6:0]  row_idx_out;
	logic [6:0]  column_idx_out;
	logic        pixel_valid_out;
	logic [9:0]  confidence_pixel_bit_data;
	logic [15:0] disparity_pixel_bit_data;

	// ------------------------------------------------------------------------
	// DUT instantiation
	// ------------------------------------------------------------------------
	top_level DUT (
		.CLOCK_50(clock_80),
		.PIXEL_BIT_DATA(sim_pixel_bit_data),
		.PIXEL_VALID_IN(pixel_valid_in),
		.SOC_IN(soc_in),
		.EOC_IN(eoc_in),
		.SOLF_IN(solf_in),
		.EOLF_IN(eolf_in),

		.SOLF_OUT(solf_out),
		.EOLF_OUT(eolf_out),
		.ROW_IDX_OUT(row_idx_out),
		.COLUMN_IDX_OUT(column_idx_out),
		.PIXEL_VALID_OUT(pixel_valid_out),
		.CONFIDENCE_PIXEL_BIT_DATA(confidence_pixel_bit_data),
		.DISPARITY_PIXEL_BIT_DATA(disparity_pixel_bit_data)
	);

	// ------------------------------------------------------------------------
	// Output capture memories
	// ------------------------------------------------------------------------
	logic                    out_solf_mem          [0:OUT_MAX_DEPTH-1];
	logic                    out_eolf_mem          [0:OUT_MAX_DEPTH-1];
	logic                    out_valid_mem         [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_row_idx_mem       [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_column_idx_mem    [0:OUT_MAX_DEPTH-1];
	logic [9:0]              out_conf_pixel_mem    [0:OUT_MAX_DEPTH-1];
	logic [15:0]             out_weighted_disp_mem [0:OUT_MAX_DEPTH-1];

	int out_idx;
	int OUT_DEPTH;

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
	// Load 1-bit MIF
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

	// ------------------------------------------------------------------------
	// Load 24-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_24(
		input string mif_path,
		input int depth,
		output logic [23:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [23:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 24'd0;
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
			data = 24'd0;
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
	// Write 1-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_1_out(
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

	// ------------------------------------------------------------------------
	// Write 7-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_7_out(
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

	// ------------------------------------------------------------------------
	// Write 10-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_10_out(
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

	// ------------------------------------------------------------------------
	// Write 16-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_16_out(
		input string mif_path,
		input int depth,
		input logic [15:0] mem [0:OUT_MAX_DEPTH-1]
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
	// Clear output memories
	// ------------------------------------------------------------------------
	task automatic clear_output_memories;
		begin
			out_idx   = 0;
			OUT_DEPTH = 0;

			for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
				out_solf_mem[k]          = 1'b0;
				out_eolf_mem[k]          = 1'b0;
				out_valid_mem[k]         = 1'b0;
				out_row_idx_mem[k]       = '0;
				out_column_idx_mem[k]    = '0;
				out_conf_pixel_mem[k]    = 10'd0;
				out_weighted_disp_mem[k] = 24'd0;
			end
		end
	endtask

	// ------------------------------------------------------------------------
	// Capture all outputs every cycle
	// ------------------------------------------------------------------------
	always_ff @(posedge clock_80) begin
		if (out_idx < OUT_MAX_DEPTH) begin
			out_solf_mem[out_idx]          <= solf_out;
			out_eolf_mem[out_idx]          <= eolf_out;
			out_valid_mem[out_idx]         <= pixel_valid_out;
			out_row_idx_mem[out_idx]       <= row_idx_out;
			out_column_idx_mem[out_idx]    <= column_idx_out;
			out_conf_pixel_mem[out_idx]    <= confidence_pixel_bit_data;
			out_weighted_disp_mem[out_idx] <= disparity_pixel_bit_data;

			out_idx <= out_idx + 1;
		end
		else begin
			$fatal(1, "ERROR: Output capture overflow. Increase OUT_MAX_DEPTH.");
		end
	end

	// ------------------------------------------------------------------------
	// Main simulation
	// ------------------------------------------------------------------------
	int i;

	initial begin
		$dumpfile("dump_tl.vcd");
		$dumpvars(0, top_level_tb);

		DEPTH = read_depth_from_mif(IN_PIXEL_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d (bad).", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d. Increase MAX_DEPTH.", DEPTH, MAX_DEPTH);
		end

		if ((4 + WARMUP_CYCLES + DEPTH + EXTRA_TAIL + 1) > OUT_MAX_DEPTH) begin
			$fatal(
				1,
				"ERROR: OUT_MAX_DEPTH too small. Need > %0d but OUT_MAX_DEPTH=%0d.",
				(4 + WARMUP_CYCLES + DEPTH + EXTRA_TAIL + 1),
				OUT_MAX_DEPTH
			);
		end

		$display("INFO: Loading top_level input MIFs from: %s", IN_DIR);
		$display("INFO: Writing output MIFs to: %s", OUT_DIR);

		load_mif_24(IN_PIXEL_MIF, DEPTH, pixel_mem);
		load_mif_1 (IN_VALID_MIF, DEPTH, valid_mem);
		load_mif_1 (IN_SOC_MIF,   DEPTH, soc_mem);
		load_mif_1 (IN_EOC_MIF,   DEPTH, eoc_mem);
		load_mif_1 (IN_SOLF_MIF,  DEPTH, solf_mem);
		load_mif_1 (IN_EOLF_MIF,  DEPTH, eolf_mem);

		clear_output_memories();

		repeat (4) @(posedge clock_80);

		// Warm-up cycles
		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_80);

			sim_pixel_bit_data <= 24'd0;
			pixel_valid_in     <= 1'b0;
			soc_in             <= 1'b0;
			eoc_in             <= 1'b0;
			solf_in            <= 1'b0;
			eolf_in            <= 1'b0;
		end

		// Drive input stream
		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_80);

			sim_pixel_bit_data <= pixel_mem[i];
			pixel_valid_in     <= valid_mem[i];
			soc_in             <= soc_mem[i];
			eoc_in             <= eoc_mem[i];
			solf_in            <= solf_mem[i];
			eolf_in            <= eolf_mem[i];
		end

		// Tail drain
		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_80);

			sim_pixel_bit_data <= 24'd0;
			pixel_valid_in     <= 1'b0;
			soc_in             <= 1'b0;
			eoc_in             <= 1'b0;
			solf_in            <= 1'b0;
			eolf_in            <= 1'b0;
		end

		@(posedge clock_80);

		OUT_DEPTH = out_idx;

		$display("INFO: Writing top_level outputs (depth=%0d) to %s", OUT_DEPTH, OUT_DIR);

		write_mif_1_out ({OUT_DIR, "/", OUT_SOLF_MIF},          OUT_DEPTH, out_solf_mem);
		write_mif_1_out ({OUT_DIR, "/", OUT_EOLF_MIF},          OUT_DEPTH, out_eolf_mem);
		write_mif_1_out ({OUT_DIR, "/", OUT_PIXEL_VALID_MIF},   OUT_DEPTH, out_valid_mem);
		write_mif_7_out ({OUT_DIR, "/", OUT_ROW_IDX_MIF},       OUT_DEPTH, out_row_idx_mem);
		write_mif_7_out ({OUT_DIR, "/", OUT_COLUMN_IDX_MIF},    OUT_DEPTH, out_column_idx_mem);
		write_mif_10_out({OUT_DIR, "/", OUT_CONF_PIXEL_MIF},    OUT_DEPTH, out_conf_pixel_mem);
		write_mif_16_out({OUT_DIR, "/", OUT_WEIGHTED_DISP_MIF}, OUT_DEPTH, out_weighted_disp_mem);

		$display("INFO: top_level testbench finished.");
		$finish;
	end

endmodule