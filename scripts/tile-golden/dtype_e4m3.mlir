cuda_tile.module @m {
  entry @dtype_e4m3(%arg0: tile<ptr<f8E4M3FN>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f8E4M3FN>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf8E4M3FN, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E4M3FN, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf8E4M3FN, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf8E4M3FN>, token
    %9 = ftof %7 rounding<nearest_even> : tile<128xf8E4M3FN> -> tile<128xf64>
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
    %25 = ftof %23 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %26 = ftof %25 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %27 = bitcast %25 : tile<128xf32> -> tile<128xi32>
    %28 = bitcast %23 : tile<128xf64> -> tile<128xi64>
    %29 = constant <i64: 9218868437227405312> : tile<128xi64>
    %30 = andi %28, %29 : tile<128xi64>
    %31 = cmpi not_equal %30, %29, signed : tile<128xi64> -> tile<128xi1>
    %32 = cmpf not_equal unordered %26, %23 : tile<128xf64> -> tile<128xi1>
    %33 = andi %31, %32 : tile<128xi1>
    %34 = constant <i32: 1> : tile<128xi32>
    %35 = ori %27, %34 : tile<128xi32>
    %36 = select %33, %35, %27 : tile<128xi1>, tile<128xi32>
    %37 = bitcast %36 : tile<128xi32> -> tile<128xf32>
    %38 = ftof %37 rounding<nearest_even> : tile<128xf32> -> tile<128xf8E4M3FN>
    %39 = ftof %38 rounding<nearest_even> : tile<128xf8E4M3FN> -> tile<128xf64>
    %40 = reshape %39 : tile<128xf64> -> tile<1x128xf64>
    %41 = constant <i32: 2> : tile<i32>
    %42 = muli %15, %41 : tile<i32>
    %43 = constant <i32: 1> : tile<i32>
    %44 = addi %42, %43 : tile<i32>
    %45 = store_view_tko weak %40, %13[%44, %4] token=%19 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
