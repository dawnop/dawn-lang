cuda_tile.module @m {
  entry @mmaf_scaled_e4m3(%arg0: tile<ptr<f8E4M3FN>>, %arg1: tile<ptr<f8E4M3FN>>, %arg2: tile<ptr<f8E8M0FNU>>, %arg3: tile<ptr<f8E8M0FNU>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f8E4M3FN>>
    %2 = make_tensor_view %1, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf8E4M3FN, strides=[64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x64), padding_value = zero, tensor_view<32x64xf8E4M3FN, strides=[64, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x64), padding_value = zero, tensor_view<32x64xf8E4M3FN, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x64xf8E4M3FN>, token
    %12 = assume div_by<16>, %arg1 : tile<ptr<f8E4M3FN>>
    %13 = make_tensor_view %12, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf8E4M3FN, strides=[32, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x32xf8E4M3FN, strides=[32, 1]>, dim_map=[0, 1]>
    %15, %16 = load_view_tko weak %14[%4, %8] token=%11 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x32xf8E4M3FN, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf8E4M3FN>, token
    %17 = assume div_by<16>, %arg2 : tile<ptr<f8E8M0FNU>>
    %18 = make_tensor_view %17, shape = [32, 2], strides = [2, 1] : tensor_view<32x2xf8E8M0FNU, strides=[2, 1]>
    %19 = make_partition_view %18 : partition_view<tile=(32x2), padding_value = zero, tensor_view<32x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>
    %20, %21 = load_view_tko weak %19[%4, %8] token=%16 : partition_view<tile=(32x2), padding_value = zero, tensor_view<32x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x2xf8E8M0FNU>, token
    %22 = assume div_by<16>, %arg3 : tile<ptr<f8E8M0FNU>>
    %23 = make_tensor_view %22, shape = [2, 32], strides = [32, 1] : tensor_view<2x32xf8E8M0FNU, strides=[32, 1]>
    %24 = make_partition_view %23 : partition_view<tile=(2x32), padding_value = zero, tensor_view<2x32xf8E8M0FNU, strides=[32, 1]>, dim_map=[0, 1]>
    %25, %26 = load_view_tko weak %24[%4, %8] token=%21 : partition_view<tile=(2x32), padding_value = zero, tensor_view<2x32xf8E8M0FNU, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x32xf8E8M0FNU>, token
    %27 = constant <f32: 0.0> : tile<32x32xf32>
    %28 = mmaf_scaled %10, %15, %27, %20, %25 : tile<32x64xf8E4M3FN>, tile<64x32xf8E4M3FN>, tile<32x32xf32>, tile<32x2xf8E8M0FNU>, tile<2x32xf8E8M0FNU>
    %29 = ftof %28 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xf64>
    %30 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %32 = make_partition_view %31 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %33 = store_view_tko weak %29, %32[%4, %8] token=%26 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
