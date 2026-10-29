cuda_tile.module @m {
  entry @dtype_e2m1(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [64], strides = [1] : tensor_view<64xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(16), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<16xi32>, token
    %9 = pack %7 : tile<16xi32> -> tile<64xi8>
    %10 = unpack %9 : tile<64xi8> -> tile<128xf4E2M1FN>
    %11 = ftof %10 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %12 = reshape %11 : tile<128xf64> -> tile<1x128xf64>
    %13 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [2, 512], strides = [512, 1] : tensor_view<2x512xf64, strides=[512, 1]>
    %15 = make_partition_view %14 : partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19 = constant <i32: 2> : tile<i32>
    %20 = muli %17, %19 : tile<i32>
    %21 = store_view_tko weak %12, %15[%20, %4] token=%0 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %25, %26 = load_view_tko weak %24[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %27 = ftof %25 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %28 = ftof %27 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %29 = bitcast %27 : tile<128xf32> -> tile<128xi32>
    %30 = bitcast %25 : tile<128xf64> -> tile<128xi64>
    %31 = constant <i64: 9218868437227405312> : tile<128xi64>
    %32 = andi %30, %31 : tile<128xi64>
    %33 = cmpi not_equal %32, %31, signed : tile<128xi64> -> tile<128xi1>
    %34 = cmpf not_equal unordered %28, %25 : tile<128xf64> -> tile<128xi1>
    %35 = andi %33, %34 : tile<128xi1>
    %36 = constant <i32: 1> : tile<128xi32>
    %37 = ori %29, %36 : tile<128xi32>
    %38 = select %35, %37, %29 : tile<128xi1>, tile<128xi32>
    %39 = bitcast %38 : tile<128xi32> -> tile<128xf32>
    %40 = cmpf not_equal unordered %25, %25 : tile<128xf64> -> tile<128xi1>
    %41 = constant <f32: 0.0> : tile<128xf32>
    %42 = select %40, %41, %39 : tile<128xi1>, tile<128xf32>
    %43 = ftof %42 rounding<nearest_even> : tile<128xf32> -> tile<128xf4E2M1FN>
    %44 = ftof %43 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %45 = reshape %44 : tile<128xf64> -> tile<1x128xf64>
    %46 = constant <i32: 2> : tile<i32>
    %47 = muli %17, %46 : tile<i32>
    %48 = constant <i32: 1> : tile<i32>
    %49 = addi %47, %48 : tile<i32>
    %50 = store_view_tko weak %45, %15[%49, %4] token=%21 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<2x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
