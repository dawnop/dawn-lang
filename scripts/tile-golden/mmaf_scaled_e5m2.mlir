cuda_tile.module @m {
  entry @mmaf_scaled_e5m2(%arg0: tile<ptr<f8E5M2>>, %arg1: tile<ptr<f8E5M2>>, %arg2: tile<ptr<f8E8M0FNU>>, %arg3: tile<ptr<f8E8M0FNU>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f8E5M2>>
    %2 = make_tensor_view %1, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf8E5M2, strides=[64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf8E5M2>, token
    %12 = assume div_by<16>, %arg1 : tile<ptr<f8E5M2>>
    %13 = make_tensor_view %12, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf8E5M2, strides=[64, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>
    %15, %16 = load_view_tko weak %14[%4, %8] token=%0 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf8E5M2, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf8E5M2>, token
    %17 = assume div_by<16>, %arg2 : tile<ptr<f8E8M0FNU>>
    %18 = make_tensor_view %17, shape = [64, 2], strides = [2, 1] : tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>
    %19 = make_partition_view %18 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>
    %20, %21 = load_view_tko weak %19[%4, %8] token=%0 : partition_view<tile=(64x2), padding_value = zero, tensor_view<64x2xf8E8M0FNU, strides=[2, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x2xf8E8M0FNU>, token
    %22 = assume div_by<16>, %arg3 : tile<ptr<f8E8M0FNU>>
    %23 = make_tensor_view %22, shape = [2, 64], strides = [64, 1] : tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>
    %24 = make_partition_view %23 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>
    %25, %26 = load_view_tko weak %24[%4, %8] token=%0 : partition_view<tile=(2x64), padding_value = zero, tensor_view<2x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x64xf8E8M0FNU>, token
    %27 = constant <f32: 0.0> : tile<64x64xf32>
    %28 = mmaf_scaled %10, %15, %27, %20, %25 : tile<64x64xf8E5M2>, tile<64x64xf8E5M2>, tile<64x64xf32>, tile<64x2xf8E8M0FNU>, tile<2x64xf8E8M0FNU>
    %29 = ftof %28 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xf64>
    %30 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %32 = make_partition_view %31 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %33 = store_view_tko weak %29, %32[%4, %8] token=%0 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
