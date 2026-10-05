cuda_tile.module @m {
  entry @dtype_i16(%arg0: tile<ptr<i16>>, %arg1: tile<ptr<i16>>, %arg2: tile<ptr<i16>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i16>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi16, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi16>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<i16>>
    %10 = make_tensor_view %9, shape = [512], strides = [1] : tensor_view<512xi16, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi16>, token
    %14 = addi %7, %12 : tile<128xi16>
    %15 = reshape %14 : tile<128xi16> -> tile<1x128xi16>
    %16 = assume div_by<16>, %arg2 : tile<ptr<i16>>
    %17 = make_tensor_view %16, shape = [5, 512], strides = [512, 1] : tensor_view<5x512xi16, strides=[512, 1]>
    %18 = make_partition_view %17 : partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>
    %19, %20, %21 = get_tile_block_id : tile<i32>
    %22 = constant <i32: 8> : tile<i32>
    %23 = muli %20, %22 : tile<i32>
    %24 = store_view_tko weak %15, %18[%23, %4] token=%13 : tile<1x128xi16>, partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %25 = subi %7, %12 : tile<128xi16>
    %26 = reshape %25 : tile<128xi16> -> tile<1x128xi16>
    %27 = constant <i32: 8> : tile<i32>
    %28 = muli %20, %27 : tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30 = addi %28, %29 : tile<i32>
    %31 = store_view_tko weak %26, %18[%30, %4] token=%24 : tile<1x128xi16>, partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %32 = muli %7, %12 : tile<128xi16>
    %33 = reshape %32 : tile<128xi16> -> tile<1x128xi16>
    %34 = constant <i32: 8> : tile<i32>
    %35 = muli %20, %34 : tile<i32>
    %36 = constant <i32: 2> : tile<i32>
    %37 = addi %35, %36 : tile<i32>
    %38 = store_view_tko weak %33, %18[%37, %4] token=%31 : tile<1x128xi16>, partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %39 = constant <i16: 3> : tile<128xi16>
    %40 = shli %7, %39 : tile<128xi16>
    %41 = constant <i16: 2> : tile<128xi16>
    %42 = shri %40, %41 signed : tile<128xi16>
    %43 = reshape %42 : tile<128xi16> -> tile<1x128xi16>
    %44 = constant <i32: 8> : tile<i32>
    %45 = muli %20, %44 : tile<i32>
    %46 = constant <i32: 3> : tile<i32>
    %47 = addi %45, %46 : tile<i32>
    %48 = store_view_tko weak %43, %18[%47, %4] token=%38 : tile<1x128xi16>, partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %49 = itof %7 signed rounding<nearest_even> : tile<128xi16> -> tile<128xf64>
    %50 = ftoi %49 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi16>
    %51 = reshape %50 : tile<128xi16> -> tile<1x128xi16>
    %52 = constant <i32: 8> : tile<i32>
    %53 = muli %20, %52 : tile<i32>
    %54 = constant <i32: 4> : tile<i32>
    %55 = addi %53, %54 : tile<i32>
    %56 = store_view_tko weak %51, %18[%55, %4] token=%48 : tile<1x128xi16>, partition_view<tile=(1x128), padding_value = zero, tensor_view<5x512xi16, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
