`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Standard_run_fao_tb.do
*/

module fused_aligned_output_tb;

	// ------------------------------------------------------------------------
	// Clock
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 20;

	logic clock_50 = 1'b0;
	always #(TCLK_NS/2) clock_50 = ~clock_50;

	// ------------------------------------------------------------------------
	// Parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM    = 128;
	localparam int unsigned STORAGE_ADDR_W = 2 * $clog2(IMAGE_DIM);

	// ------------------------------------------------------------------------
	// Paths
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Standard/tb/fao/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Standard/tb/fao/output_data";

	// ------------------------------------------------------------------------
	// Input filenames : confidence stream
	// ------------------------------------------------------------------------
	localparam string IN_CONF_COLUMN_IDX_MIF  = {IN_DIR, "/SIM_CONF_COLUMN_IDX_IN.mif"};
	localparam string IN_CONF_ORIENTATION_MIF = {IN_DIR, "/SIM_CONF_ORIENTATION_IN.mif"};
	localparam string IN_CONF_PIXEL_MIF       = {IN_DIR, "/SIM_CONF_PIXEL_IN.mif"};
	localparam string IN_CONF_ROW_IDX_MIF     = {IN_DIR, "/SIM_CONF_ROW_IDX_IN.mif"};
	localparam string IN_CONF_VALID_MIF       = {IN_DIR, "/SIM_CONF_VALID_IN.mif"};

	// ------------------------------------------------------------------------
	// Input filenames : disparity stream
	// ------------------------------------------------------------------------
	localparam string IN_DISP_COLUMN_IDX_MIF  = {IN_DIR, "/SIM_DISP_COLUMN_IDX_IN.mif"};
	localparam string IN_DISP_ORIENTATION_MIF = {IN_DIR, "/SIM_DISP_ORIENTATION_IN.mif"};
	localparam string IN_DISP_PIXEL_MIF       = {IN_DIR, "/SIM_DISP_PIXEL_IN.mif"};
	localparam string IN_DISP_ROW_IDX_MIF     = {IN_DIR, "/SIM_DISP_ROW_IDX_IN.mif"};
	localparam string IN_DISP_VALID_MIF       = {IN_DIR, "/SIM_DISP_VALID_IN.mif"};

	// ------------------------------------------------------------------------
	// Output filenames
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
	localparam int MAX_DEPTH     = 417000;
	localparam int WARMUP_CYCLES = 8;
	localparam int EXTRA_TAIL    = 512;
	localparam int OUT_MAX_DEPTH = 4 + WARMUP_CYCLES + MAX_DEPTH + EXTRA_TAIL + 64;

	// ------------------------------------------------------------------------
	// Alignment
	// ------------------------------------------------------------------------
	localparam int CONF_TRIM_OFFSET = 0;
	localparam int DISP_TRIM_OFFSET = 0;

	int DEPTH_CONF = 0;
	int DEPTH_DISP = 0;
	int DEPTH      = 0;

	// ------------------------------------------------------------------------
	// Input memories : confidence stream
	// ------------------------------------------------------------------------
	logic                    conf_valid_mem       [0:MAX_DEPTH-1];
	logic [14:0]             conf_pixel_mem       [0:MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] conf_row_idx_mem     [0:MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] conf_column_idx_mem  [0:MAX_DEPTH-1];
	logic                    conf_orientation_mem [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Input memories : disparity stream
	// ------------------------------------------------------------------------
	logic                    disp_valid_mem       [0:MAX_DEPTH-1];
	logic signed [31:0]      disp_pixel_mem       [0:MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] disp_row_idx_mem     [0:MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] disp_column_idx_mem  [0:MAX_DEPTH-1];
	logic                    disp_orientation_mem [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic                     confidence_valid_in       = 1'b0;
	logic [14:0]              confidence_pixel_in       = 15'd0;
	logic [$clog2(IMAGE_DIM)-1:0]  confidence_row_idx_in     = '0;
	logic [$clog2(IMAGE_DIM)-1:0]  confidence_column_idx_in  = '0;
	logic                     confidence_orientation_in = 1'b0;

	logic                     disparity_valid_in        = 1'b0;
	logic [31:0]              disparity_pixel_in        = 32'd0;
	logic [$clog2(IMAGE_DIM)-1:0]  disparity_row_idx_in      = '0;
	logic [$clog2(IMAGE_DIM)-1:0]  disparity_column_idx_in   = '0;
	logic                     disparity_orientation_in  = 1'b0;

	logic                     shared_banks_available    = 1'b0;

	// ------------------------------------------------------------------------
	// Shared storage signals
	// ------------------------------------------------------------------------
	logic                             epic_storage_we [0:11];
	logic                             epic_storage_we_8v;
	logic [STORAGE_ADDR_W-1:0]        epic_storage_wr_addr [0:11];
	logic [STORAGE_ADDR_W-1:0]        epic_storage_wr_addr_8v;
	logic [14:0]                      epic_storage_wr_data;
	logic [STORAGE_ADDR_W-1:0]        epic_storage_rd_addr;
	logic [14:0]                      epic_storage_rd_data [0:11];
	logic [14:0]                      epic_storage_rd_data_8v;

	logic                             fao_shared_we [0:3];
	logic [STORAGE_ADDR_W-1:0]        fao_shared_wr_addr [0:3];
	logic [14:0]                      fao_shared_wr_data [0:3];
	logic [STORAGE_ADDR_W-1:0]        fao_shared_rd_addr [0:3];
	logic [14:0]                      fao_shared_rd_data [0:3];

	// ------------------------------------------------------------------------
	// DUT outputs
	// ------------------------------------------------------------------------
	logic                     solf_out;
	logic                     eolf_out;
	logic                     pixel_valid_out;
	logic [$clog2(IMAGE_DIM)-1:0]  row_idx_out;
	logic [$clog2(IMAGE_DIM)-1:0]  column_idx_out;
	logic [14:0]              confidence_pixel_bit_data;
	logic [23:0]              weighted_disparity_pixel_bit_data;

	// ------------------------------------------------------------------------
	// Shared storage instantiation
	// ------------------------------------------------------------------------
	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM)
	) SHARED_STORAGE (
		.clk(clock_50),
		.takeover_banks_5_to_8(shared_banks_available),
		.epi_read_banks_5_to_8_active(1'b0),

		.epi_we(epic_storage_we),
		.epi_we_8v(epic_storage_we_8v),
		.epi_wr_addr(epic_storage_wr_addr),
		.epi_wr_addr_8v(epic_storage_wr_addr_8v),
		.epi_wr_data(epic_storage_wr_data),
		.epi_rd_addr(epic_storage_rd_addr),
		.epi_rd_data(epic_storage_rd_data),
		.epi_rd_data_8v(epic_storage_rd_data_8v),

		.fao_we(fao_shared_we),
		.fao_wr_addr(fao_shared_wr_addr),
		.fao_wr_data(fao_shared_wr_data),
		.fao_rd_addr(fao_shared_rd_addr),
		.fao_rd_data(fao_shared_rd_data)
	);

	// ------------------------------------------------------------------------
	// Tie off unused EPI side
	// ------------------------------------------------------------------------
	always_comb begin
		for (int i = 0; i < 12; i++) begin
			epic_storage_we[i]      = 1'b0;
			epic_storage_wr_addr[i] = '0;
		end

		epic_storage_we_8v      = 1'b0;
		epic_storage_wr_addr_8v = '0;
		epic_storage_wr_data    = '0;
		epic_storage_rd_addr    = '0;
	end

	// ------------------------------------------------------------------------
	// DUT instantiation
	// ------------------------------------------------------------------------
	fused_aligned_output #(
		.IMAGE_DIM(IMAGE_DIM)
	) DUT (
		.clk(clkock_50_fix(clock_50)),

		.confidence_valid_in(confidence_valid_in),
		.confidence_pixel_in(confidence_pixel_in),
		.confidence_row_idx_in(confidence_row_idx_in),
		.confidence_column_idx_in(confidence_column_idx_in),
		.confidence_orientation_in(confidence_orientation_in),

		.disparity_valid_in(disparity_valid_in),
		.disparity_pixel_in(disparity_pixel_in),
		.disparity_row_idx_in(disparity_row_idx_in),
		.disparity_column_idx_in(disparity_column_idx_in),
		.disparity_orientation_in(disparity_orientation_in),

		.shared_banks_available(shared_banks_available),
		.shared_we(fao_shared_we),
		.shared_wr_addr(fao_shared_wr_addr),
		.shared_wr_data(fao_shared_wr_data),
		.shared_rd_addr(fao_shared_rd_addr),
		.shared_rd_data(fao_shared_rd_data),

		.solf_out(solf_out),
		.eolf_out(eolf_out),
		.pixel_valid_out(pixel_valid_out),
		.row_idx_out(row_idx_out),
		.column_idx_out(column_idx_out),
		.confidence_pixel_bit_data(confidence_pixel_bit_data),
		.weighted_disparity_pixel_bit_data(weighted_disparity_pixel_bit_data)
	);

	function automatic logic clkock_50_fix(input logic c);
		clkock_50_fix = c;
	endfunction

	// ------------------------------------------------------------------------
	// Output capture memories
	// ------------------------------------------------------------------------
	logic                    out_solf_mem          [0:OUT_MAX_DEPTH-1];
	logic                    out_eolf_mem          [0:OUT_MAX_DEPTH-1];
	logic                    out_valid_mem         [0:OUT_MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] out_row_idx_mem       [0:OUT_MAX_DEPTH-1];
	logic [$clog2(IMAGE_DIM)-1:0] out_column_idx_mem    [0:OUT_MAX_DEPTH-1];
	logic [14:0]             out_conf_pixel_mem    [0:OUT_MAX_DEPTH-1];
	logic [23:0]             out_weighted_disp_mem [0:OUT_MAX_DEPTH-1];

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
	// Load 7-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_7(
		input string mif_path,
		input int depth,
		output logic [$clog2(IMAGE_DIM)-1:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [$clog2(IMAGE_DIM)-1:0] data;
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

	// ------------------------------------------------------------------------
	// Load 15-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_15(
		input string mif_path,
		input int depth,
		output logic [14:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [14:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 15'd0;
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
			data = 15'd0;
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
	// Load 32-bit signed MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_32_signed(
		input string mif_path,
		input int depth,
		output logic signed [31:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic signed [31:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 32'sd0;
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
			data = 32'sd0;
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
		input logic [$clog2(IMAGE_DIM)-1:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=%0d;", $clog2(IMAGE_DIM));
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
	// Write 15-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_15_out(
		input string mif_path,
		input int depth,
		input logic [14:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=15;");
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
	// Write 24-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_24_out(
		input string mif_path,
		input int depth,
		input logic [23:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=24;");
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
				out_conf_pixel_mem[k]    = 15'd0;
				out_weighted_disp_mem[k] = 24'd0;
			end
		end
	endtask

	// ------------------------------------------------------------------------
	// Capture all outputs every cycle
	// ------------------------------------------------------------------------
	always_ff @(posedge clock_50) begin
		if (out_idx < OUT_MAX_DEPTH) begin
			out_solf_mem[out_idx]          <= solf_out;
			out_eolf_mem[out_idx]          <= eolf_out;
			out_valid_mem[out_idx]         <= pixel_valid_out;
			out_row_idx_mem[out_idx]       <= row_idx_out;
			out_column_idx_mem[out_idx]    <= column_idx_out;
			out_conf_pixel_mem[out_idx]    <= confidence_pixel_bit_data;
			out_weighted_disp_mem[out_idx] <= weighted_disparity_pixel_bit_data;

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
		$dumpfile("dump_fao.vcd");
		$dumpvars(0, fused_aligned_output_tb);

		DEPTH_CONF = read_depth_from_mif(IN_CONF_VALID_MIF);
		DEPTH_DISP = read_depth_from_mif(IN_DISP_VALID_MIF);

		if (DEPTH_CONF <= 0) begin
			$fatal(1, "ERROR: CONF DEPTH read as %0d.", DEPTH_CONF);
		end

		if (DEPTH_DISP <= 0) begin
			$fatal(1, "ERROR: DISP DEPTH read as %0d.", DEPTH_DISP);
		end

		if (DEPTH_CONF > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH_CONF=%0d exceeds MAX_DEPTH=%0d.", DEPTH_CONF, MAX_DEPTH);
		end

		if (DEPTH_DISP > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH_DISP=%0d exceeds MAX_DEPTH=%0d.", DEPTH_DISP, MAX_DEPTH);
		end

		if (DEPTH_CONF < CONF_TRIM_OFFSET) begin
			$fatal(1, "ERROR: DEPTH_CONF=%0d is smaller than CONF_TRIM_OFFSET=%0d.", DEPTH_CONF, CONF_TRIM_OFFSET);
		end

		if (DEPTH_DISP < DISP_TRIM_OFFSET) begin
			$fatal(1, "ERROR: DEPTH_DISP=%0d is smaller than DISP_TRIM_OFFSET=%0d.", DEPTH_DISP, DISP_TRIM_OFFSET);
		end

		DEPTH = ((DEPTH_CONF - CONF_TRIM_OFFSET) < (DEPTH_DISP - DISP_TRIM_OFFSET)) ?
		         (DEPTH_CONF - CONF_TRIM_OFFSET) :
		         (DEPTH_DISP - DISP_TRIM_OFFSET);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: Common aligned DEPTH=%0d.", DEPTH);
		end

		$display("INFO: Loading fused_aligned_output input MIFs from: %s", IN_DIR);
		$display("INFO: CONF depth = %0d", DEPTH_CONF);
		$display("INFO: DISP depth = %0d", DEPTH_DISP);
		$display("INFO: CONF_TRIM_OFFSET = %0d", CONF_TRIM_OFFSET);
		$display("INFO: DISP_TRIM_OFFSET = %0d", DISP_TRIM_OFFSET);
		$display("INFO: Common driven depth = %0d", DEPTH);

		load_mif_1 (IN_CONF_VALID_MIF,       DEPTH_CONF, conf_valid_mem);
		load_mif_15(IN_CONF_PIXEL_MIF,       DEPTH_CONF, conf_pixel_mem);
		load_mif_7 (IN_CONF_ROW_IDX_MIF,     DEPTH_CONF, conf_row_idx_mem);
		load_mif_7 (IN_CONF_COLUMN_IDX_MIF,  DEPTH_CONF, conf_column_idx_mem);
		load_mif_1 (IN_CONF_ORIENTATION_MIF, DEPTH_CONF, conf_orientation_mem);

		load_mif_1        (IN_DISP_VALID_MIF,       DEPTH_DISP, disp_valid_mem);
		load_mif_32_signed(IN_DISP_PIXEL_MIF,       DEPTH_DISP, disp_pixel_mem);
		load_mif_7        (IN_DISP_ROW_IDX_MIF,     DEPTH_DISP, disp_row_idx_mem);
		load_mif_7        (IN_DISP_COLUMN_IDX_MIF,  DEPTH_DISP, disp_column_idx_mem);
		load_mif_1        (IN_DISP_ORIENTATION_MIF, DEPTH_DISP, disp_orientation_mem);

		clear_output_memories();

		repeat (4) @(posedge clock_50);

		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);

			shared_banks_available <= 1'b0;

			confidence_valid_in       <= 1'b0;
			confidence_pixel_in       <= 15'd0;
			confidence_row_idx_in     <= '0;
			confidence_column_idx_in  <= '0;
			confidence_orientation_in <= 1'b0;

			disparity_valid_in        <= 1'b0;
			disparity_pixel_in        <= 32'd0;
			disparity_row_idx_in      <= '0;
			disparity_column_idx_in   <= '0;
			disparity_orientation_in  <= 1'b0;
		end

		// Enable shared banks before the actual FAO stream begins
		@(posedge clock_50);
		shared_banks_available <= 1'b1;

		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			shared_banks_available <= 1'b1;

			confidence_valid_in       <= conf_valid_mem[i + CONF_TRIM_OFFSET];
			confidence_pixel_in       <= conf_pixel_mem[i + CONF_TRIM_OFFSET];
			confidence_row_idx_in     <= conf_row_idx_mem[i + CONF_TRIM_OFFSET];
			confidence_column_idx_in  <= conf_column_idx_mem[i + CONF_TRIM_OFFSET];
			confidence_orientation_in <= conf_orientation_mem[i + CONF_TRIM_OFFSET];

			disparity_valid_in        <= disp_valid_mem[i + DISP_TRIM_OFFSET];
			disparity_pixel_in        <= disp_pixel_mem[i + DISP_TRIM_OFFSET];
			disparity_row_idx_in      <= disp_row_idx_mem[i + DISP_TRIM_OFFSET];
			disparity_column_idx_in   <= disp_column_idx_mem[i + DISP_TRIM_OFFSET];
			disparity_orientation_in  <= disp_orientation_mem[i + DISP_TRIM_OFFSET];
		end

		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			shared_banks_available <= 1'b1;

			confidence_valid_in       <= 1'b0;
			confidence_pixel_in       <= 15'd0;
			confidence_row_idx_in     <= '0;
			confidence_column_idx_in  <= '0;
			confidence_orientation_in <= 1'b0;

			disparity_valid_in        <= 1'b0;
			disparity_pixel_in        <= 32'd0;
			disparity_row_idx_in      <= '0;
			disparity_column_idx_in   <= '0;
			disparity_orientation_in  <= 1'b0;
		end

		@(posedge clock_50);

		OUT_DEPTH = out_idx;

		$display("INFO: Writing fused_aligned_output outputs (depth=%0d) to %s", OUT_DEPTH, OUT_DIR);

		write_mif_1_out ({OUT_DIR, "/", OUT_SOLF_MIF},          OUT_DEPTH, out_solf_mem);
		write_mif_1_out ({OUT_DIR, "/", OUT_EOLF_MIF},          OUT_DEPTH, out_eolf_mem);
		write_mif_1_out ({OUT_DIR, "/", OUT_PIXEL_VALID_MIF},   OUT_DEPTH, out_valid_mem);
		write_mif_7_out ({OUT_DIR, "/", OUT_ROW_IDX_MIF},       OUT_DEPTH, out_row_idx_mem);
		write_mif_7_out ({OUT_DIR, "/", OUT_COLUMN_IDX_MIF},    OUT_DEPTH, out_column_idx_mem);
		write_mif_15_out({OUT_DIR, "/", OUT_CONF_PIXEL_MIF},    OUT_DEPTH, out_conf_pixel_mem);
		write_mif_24_out({OUT_DIR, "/", OUT_WEIGHTED_DISP_MIF}, OUT_DEPTH, out_weighted_disp_mem);

		$display("INFO: fused_aligned_output testbench finished.");
		$finish;
	end

endmodule