cuda_tile.module @m {
  entry @dtype_e8m0(%arg0: tile<ptr<f8E8M0FNU>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f8E8M0FNU>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf8E8M0FNU, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E8M0FNU, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E8M0FNU, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf8E8M0FNU>, token
    %9 = ftof %7 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf64>
    %10 = reshape %9 : tile<128xf64> -> tile<1x128xf64>
    %11 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %12 = make_tensor_view %11, shape = [2, 512], strides = [512, 1] : tensor_view<2x512xf64, strides=[512, 1]>
    %13 = make_partition_view %12 : partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>
    %14, %15, %16 = get_tile_block_id : tile<i32>
    %17 = constant <i32: 2> : tile<i32>
    %18 = muli %15, %17 : tile<i32>
    %19 = store_view_tko weak %10, %13[%18, %4] token=%0 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %20 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %23, %24 = load_view_tko weak %22[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %25 = ftof %23 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %26 = bitcast %25 : tile<128xf32> -> tile<128xi32>
    %27 = constant <i32: 2147483647> : tile<128xi32>
    %28 = andi %26, %27 : tile<128xi32>
    %29 = constant <i32: 4194304> : tile<128xi32>
    %30 = cmpi less_than %28, %29, signed : tile<128xi32> -> tile<128xi1>
    %31 = select %30, %29, %28 : tile<128xi1>, tile<128xi32>
    %32 = constant <i32: 2130706432> : tile<128xi32>
    %33 = cmpi greater_than %28, %32, signed : tile<128xi32> -> tile<128xi1>
    %34 = select %33, %32, %31 : tile<128xi1>, tile<128xi32>
    %35 = constant <i32: 2139095040> : tile<128xi32>
    %36 = cmpi greater_than %28, %35, signed : tile<128xi32> -> tile<128xi1>
    %37 = constant <i32: 2143289344> : tile<128xi32>
    %38 = select %36, %37, %34 : tile<128xi1>, tile<128xi32>
    %39 = bitcast %38 : tile<128xi32> -> tile<128xf32>
    %40 = ftof %39 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %41 = ftof %40 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %42 = ftof %41 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %43 = reshape %42 : tile<128xf64> -> tile<1x128xf64>
    %44 = constant <i32: 2> : tile<i32>
    %45 = muli %15, %44 : tile<i32>
    %46 = constant <i32: 1> : tile<i32>
    %47 = addi %45, %46 : tile<i32>
    %48 = store_view_tko weak %43, %13[%47, %4] token=%19 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
