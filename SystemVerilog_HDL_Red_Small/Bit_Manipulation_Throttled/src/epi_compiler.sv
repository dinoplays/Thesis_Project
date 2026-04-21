module epi_compiler #(
	parameter int unsigned IMAGE_DIM    = 64,
	parameter int unsigned IMAGE_DIM_BS = 6
)(
	input  wire                                   clk,
	input  wire                                   pixel_valid_in,
	input  wire                                   soc_in,
	input  wire                                   eoc_in,
	input  wire                                   solf_in,
	input  wire                                   eolf_in,
	input  wire [14:0]                            pixel_in,

	// ---------------------------------------------------------------------
	// Shared storage interface
	// ---------------------------------------------------------------------
	output logic                                  storage_we [0:11],
	output logic                                  storage_we_8v,
	output logic [((2*IMAGE_DIM_BS)-1):0]         storage_wr_addr [0:11],
	output logic [((2*IMAGE_DIM_BS)-1):0]         storage_wr_addr_8v,
	output logic [14:0]                           storage_wr_data,
	output logic [((2*IMAGE_DIM_BS)-1):0]         storage_rd_addr,
	input  wire [14:0]                            storage_rd_data [0:11],
	input  wire [14:0]                            storage_rd_data_8v,
	output logic                                  shared_banks_5_to_8_released,
	output logic                                  shared_banks_5_to_8_epi_read_active,

	output logic                                  epi_valid_out,
	output logic [14:0]                           epi_column_out [0:8],
	output logic [IMAGE_DIM_BS-1:0]               epi_column_idx_out,
	output logic [IMAGE_DIM_BS-1:0]               epi_idx_out,
	output logic                                  orientation_out
);

	localparam int unsigned EPI_FRAME_PTR_W = 2 * IMAGE_DIM_BS;

	localparam logic [4:0] H_READ_CAPTURE = 5'd12;
	localparam logic [4:0] V_READ_CAPTURE = 5'd16;

	logic                           in_lf_flag       = 1'b0;
	logic [4:0]                     capture_in_count = 5'd0;
	logic [IMAGE_DIM_BS-1:0]        row_in_count     = '0;
	logic [IMAGE_DIM_BS-1:0]        column_in_count  = '0;

	logic                           h_read_phase;
	logic                           h_read_phase_d;
	logic                           h_read_phase_dd;
	logic                           write_phase;
	logic                           v08_store_phase;

	logic [14:0]                    pixel_in_d         = '0;
	logic [14:0]                    pixel_in_dd        = '0;
	logic [IMAGE_DIM_BS-1:0]        row_in_count_d     = '0;
	logic [IMAGE_DIM_BS-1:0]        row_in_count_dd    = '0;
	logic [IMAGE_DIM_BS-1:0]        column_in_count_d  = '0;
	logic [IMAGE_DIM_BS-1:0]        column_in_count_dd = '0;

	logic                           vertical_output_active = 1'b0;
	logic                           vertical_start_pulse   = 1'b0;

	logic [IMAGE_DIM_BS-1:0]        v_epi_idx     = '0;
	logic [IMAGE_DIM_BS-1:0]        v_spatial_idx = '0;

	logic                           v_read_issue_d   = 1'b0;
	logic                           v_read_issue_dd  = 1'b0;
	logic [IMAGE_DIM_BS-1:0]        v_epi_idx_d      = '0;
	logic [IMAGE_DIM_BS-1:0]        v_epi_idx_dd     = '0;
	logic [IMAGE_DIM_BS-1:0]        v_spatial_idx_d  = '0;
	logic [IMAGE_DIM_BS-1:0]        v_spatial_idx_dd = '0;

	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_row_major;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_transposed;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_calc;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_frame4;

	logic [EPI_FRAME_PTR_W-1:0]     rd_addr_h_live;
	logic [EPI_FRAME_PTR_W-1:0]     rd_addr_v_post;

	// ---------------------------------------------------------------------
	// Pipelined write-command generation
	// ---------------------------------------------------------------------
	logic                           write_phase_q;
	logic                           v08_store_phase_q;
	logic [4:0]                     capture_in_count_q;
	logic [14:0]                    pixel_in_write_q;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_calc_q;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_frame4_q;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_transposed_q;
	logic [EPI_FRAME_PTR_W-1:0]     wr_addr_row_major_q;

	// ---------------------------------------------------------------------
	// Internal registered storage buses
	// ---------------------------------------------------------------------
	logic                           storage_we_r [0:11];
	logic                           storage_we_8v_r;
	logic [((2*IMAGE_DIM_BS)-1):0]  storage_wr_addr_r [0:11];
	logic [((2*IMAGE_DIM_BS)-1):0]  storage_wr_addr_8v_r;
	logic [14:0]                    storage_wr_data_r;

	// ---------------------------------------------------------------------
	// Two-cycle drain/start pipes
	// ---------------------------------------------------------------------
	logic [1:0]                     shared_release_pipe = 2'b00;
	logic [1:0]                     vertical_start_pipe = 2'b00;

	function automatic [EPI_FRAME_PTR_W-1:0] addr_row_major(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_row_major =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i};
		end
	endfunction

	function automatic [EPI_FRAME_PTR_W-1:0] addr_transposed(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_transposed =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i};
		end
	endfunction

	function automatic logic is_vertical_store_capture(
		input logic [4:0] cap_i
	);
		begin
			case (cap_i)
				5'd0,
				5'd1,
				5'd2,
				5'd3,
				5'd13,
				5'd14,
				5'd15: is_vertical_store_capture = 1'b1;
				default: is_vertical_store_capture = 1'b0;
			endcase
		end
	endfunction

	assign h_read_phase = (in_lf_flag || solf_in) &&
	                      pixel_valid_in &&
	                      (capture_in_count == H_READ_CAPTURE);

	assign write_phase = (in_lf_flag || solf_in) &&
	                     pixel_valid_in &&
	                     (capture_in_count != H_READ_CAPTURE) &&
	                     (capture_in_count != V_READ_CAPTURE);

	assign v08_store_phase = (in_lf_flag || solf_in) &&
	                         pixel_valid_in &&
	                         (capture_in_count == V_READ_CAPTURE);

	// Shared banks 5..8 must remain on EPIC reads during the horizontal read frame.
	assign shared_banks_5_to_8_epi_read_active = h_read_phase;

	assign wr_addr_row_major  = addr_row_major(row_in_count, column_in_count);
	assign wr_addr_transposed = addr_transposed(row_in_count, column_in_count);
	assign wr_addr_calc       = is_vertical_store_capture(capture_in_count) ? wr_addr_transposed
	                                                                        : wr_addr_row_major;
	assign wr_addr_frame4     = v08_store_phase ? wr_addr_transposed
	                                            : wr_addr_calc;

	assign rd_addr_h_live = wr_addr_row_major;
	assign rd_addr_v_post = addr_row_major(v_epi_idx, v_spatial_idx);

	// New shared storage adds a registered read-address stage, so output uses _dd.
	assign storage_rd_addr = vertical_output_active ? rd_addr_v_post : rd_addr_h_live;

	// ---------------------------------------------------------------------
	// Register write command one stage earlier
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Write_Command_Pipeline
		write_phase_q        <= write_phase;
		v08_store_phase_q    <= v08_store_phase;
		capture_in_count_q   <= capture_in_count;
		pixel_in_write_q     <= pixel_in;
		wr_addr_calc_q       <= wr_addr_calc;
		wr_addr_frame4_q     <= wr_addr_frame4;
		wr_addr_transposed_q <= wr_addr_transposed;
		wr_addr_row_major_q  <= wr_addr_row_major;
	end

	// ---------------------------------------------------------------------
	// Registered storage write drive
	// Only the selected bank updates its address register.
	// Inactive banks keep their previous write address.
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Registered_Storage_Write_Drive
		integer i;

		for (i = 0; i < 12; i = i + 1) begin
			storage_we_r[i] <= 1'b0;
		end

		storage_we_8v_r   <= 1'b0;
		storage_wr_data_r <= pixel_in_write_q;

		if (write_phase_q) begin
			case (capture_in_count_q)
				5'd0  : begin
					storage_we_r[0]      <= 1'b1;
					storage_wr_addr_r[0] <= wr_addr_calc_q;
				end
				5'd1  : begin
					storage_we_r[1]      <= 1'b1;
					storage_wr_addr_r[1] <= wr_addr_calc_q;
				end
				5'd2  : begin
					storage_we_r[2]      <= 1'b1;
					storage_wr_addr_r[2] <= wr_addr_calc_q;
				end
				5'd3  : begin
					storage_we_r[3]      <= 1'b1;
					storage_wr_addr_r[3] <= wr_addr_calc_q;
				end
				5'd4  : begin
					storage_we_r[4]      <= 1'b1;
					storage_wr_addr_r[4] <= wr_addr_frame4_q;
				end
				5'd5  : begin
					storage_we_r[5]      <= 1'b1;
					storage_wr_addr_r[5] <= wr_addr_calc_q;
				end
				5'd6  : begin
					storage_we_r[6]      <= 1'b1;
					storage_wr_addr_r[6] <= wr_addr_calc_q;
				end
				5'd7  : begin
					storage_we_r[7]      <= 1'b1;
					storage_wr_addr_r[7] <= wr_addr_calc_q;
				end
				5'd8  : begin
					storage_we_r[8]       <= 1'b1;
					storage_wr_addr_r[8]  <= wr_addr_row_major_q;
					storage_we_8v_r       <= 1'b1;
					storage_wr_addr_8v_r  <= wr_addr_transposed_q;
				end
				5'd9  : begin
					storage_we_r[9]      <= 1'b1;
					storage_wr_addr_r[9] <= wr_addr_calc_q;
				end
				5'd10 : begin
					storage_we_r[10]      <= 1'b1;
					storage_wr_addr_r[10] <= wr_addr_calc_q;
				end
				5'd11 : begin
					storage_we_r[11]      <= 1'b1;
					storage_wr_addr_r[11] <= wr_addr_calc_q;
				end
				5'd13 : begin
					storage_we_r[9]      <= 1'b1;
					storage_wr_addr_r[9] <= wr_addr_calc_q;
				end
				5'd14 : begin
					storage_we_r[10]      <= 1'b1;
					storage_wr_addr_r[10] <= wr_addr_calc_q;
				end
				5'd15 : begin
					storage_we_r[11]      <= 1'b1;
					storage_wr_addr_r[11] <= wr_addr_calc_q;
				end
				default: begin
				end
			endcase
		end

		if (v08_store_phase_q) begin
			storage_we_r[4]      <= 1'b1;
			storage_wr_addr_r[4] <= wr_addr_frame4_q;
		end
	end

	// ---------------------------------------------------------------------
	// Drive module outputs from internal registered buses
	// ---------------------------------------------------------------------
	always_comb begin : Drive_Storage_Buses
		integer j;

		for (j = 0; j < 12; j = j + 1) begin
			storage_we[j]      = storage_we_r[j];
			storage_wr_addr[j] = storage_wr_addr_r[j];
		end

		storage_we_8v      = storage_we_8v_r;
		storage_wr_addr_8v = storage_wr_addr_8v_r;
		storage_wr_data    = storage_wr_data_r;
	end

	// ---------------------------------------------------------------------
	// Control and metadata delay
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : LF_Control_And_Addressing
		vertical_start_pulse <= 1'b0;

		if (solf_in) begin
			in_lf_flag                   <= 1'b1;
			capture_in_count             <= 5'd0;
			row_in_count                 <= '0;
			column_in_count              <= '0;
			shared_banks_5_to_8_released <= 1'b0;
			shared_release_pipe          <= 2'b00;
			vertical_start_pipe          <= 2'b00;
		end
		else begin
			// Default shift of the two-cycle drain/start pipes every cycle.
			shared_release_pipe[1] <= shared_release_pipe[0];
			shared_release_pipe[0] <= 1'b0;

			vertical_start_pipe[1] <= vertical_start_pipe[0];
			vertical_start_pipe[0] <= 1'b0;

			if (eolf_in) begin
				in_lf_flag       <= 1'b0;
				capture_in_count <= 5'd0;
				row_in_count     <= '0;
				column_in_count  <= '0;

				// Start vertical output only after two drain cycles.
				vertical_start_pipe[0] <= 1'b1;
			end

			// After two cycles, allow FAO to take shared write banks.
			if (shared_release_pipe[1]) begin
				shared_banks_5_to_8_released <= 1'b1;
			end

			// After two cycles, request vertical post-frame readout.
			if (vertical_start_pipe[1]) begin
				vertical_start_pulse <= 1'b1;
			end
		end

		// Always shift stage-1 into stage-2
		h_read_phase_dd    <= h_read_phase_d;
		pixel_in_dd        <= pixel_in_d;
		row_in_count_dd    <= row_in_count_d;
		column_in_count_dd <= column_in_count_d;

		if ((in_lf_flag || solf_in) && pixel_valid_in) begin
			h_read_phase_d    <= h_read_phase;
			pixel_in_d        <= pixel_in;
			row_in_count_d    <= row_in_count;
			column_in_count_d <= column_in_count;

			if (soc_in) begin
				row_in_count    <= '0;
				column_in_count <= {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
			end
			else begin
				if (column_in_count == IMAGE_DIM-1) begin
					column_in_count <= '0;
					row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
				else begin
					column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end

			if (eoc_in) begin
				row_in_count    <= '0;
				column_in_count <= '0;

				if (!eolf_in && capture_in_count < 5'd16) begin
					if (capture_in_count == (H_READ_CAPTURE - 5'd1)) begin
						shared_release_pipe[0] <= 1'b1;
					end
					capture_in_count <= capture_in_count + 5'd1;
				end
			end
		end
		else begin
			// No new valid input this cycle, but preserve pipeline flow
			h_read_phase_d <= 1'b0;
		end
	end

	// ---------------------------------------------------------------------
	// Vertical post-frame readout
	// Sole writer of vertical_output_active, v_epi_idx, v_spatial_idx
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Vertical_Post_Frame_Output
		v_read_issue_d   <= 1'b0;
		v_read_issue_dd  <= v_read_issue_d;
		v_epi_idx_dd     <= v_epi_idx_d;
		v_spatial_idx_dd <= v_spatial_idx_d;

		if (solf_in) begin
			vertical_output_active <= 1'b0;
			v_epi_idx              <= '0;
			v_spatial_idx          <= '0;
			v_epi_idx_d            <= '0;
			v_spatial_idx_d        <= '0;
			v_epi_idx_dd           <= '0;
			v_spatial_idx_dd       <= '0;
			v_read_issue_dd        <= 1'b0;
		end
		else begin
			if (vertical_start_pulse) begin
				vertical_output_active <= 1'b1;
				v_epi_idx              <= '0;
				v_spatial_idx          <= '0;
			end
			else if (vertical_output_active) begin
				v_read_issue_d  <= 1'b1;
				v_epi_idx_d     <= v_epi_idx;
				v_spatial_idx_d <= v_spatial_idx;

				if (v_spatial_idx == IMAGE_DIM-1) begin
					v_spatial_idx <= '0;

					if (v_epi_idx == IMAGE_DIM-1) begin
						v_epi_idx              <= '0;
						vertical_output_active <= 1'b0;
					end
					else begin
						v_epi_idx <= v_epi_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
					end
				end
				else begin
					v_spatial_idx <= v_spatial_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end
		end
	end

	// ---------------------------------------------------------------------
	// Output
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : EPI_Output
		integer k;

		if (h_read_phase_dd) begin
			orientation_out    <= 1'b0;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= row_in_count_dd;
			epi_column_idx_out <= column_in_count_dd;

			epi_column_out[0] <= storage_rd_data[4];
			epi_column_out[1] <= storage_rd_data[5];
			epi_column_out[2] <= storage_rd_data[6];
			epi_column_out[3] <= storage_rd_data[7];
			epi_column_out[4] <= storage_rd_data[8];
			epi_column_out[5] <= storage_rd_data[9];
			epi_column_out[6] <= storage_rd_data[10];
			epi_column_out[7] <= storage_rd_data[11];
			epi_column_out[8] <= pixel_in_dd;
		end
		else if (v_read_issue_dd) begin
			orientation_out    <= 1'b1;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= v_epi_idx_dd;
			epi_column_idx_out <= v_spatial_idx_dd;

			epi_column_out[0] <= storage_rd_data[0];
			epi_column_out[1] <= storage_rd_data[1];
			epi_column_out[2] <= storage_rd_data[2];
			epi_column_out[3] <= storage_rd_data[3];
			epi_column_out[4] <= storage_rd_data_8v;
			epi_column_out[5] <= storage_rd_data[9];
			epi_column_out[6] <= storage_rd_data[10];
			epi_column_out[7] <= storage_rd_data[11];
			epi_column_out[8] <= storage_rd_data[4];
		end
		else begin
			epi_valid_out <= 1'b0;
		end
	end

endmodule