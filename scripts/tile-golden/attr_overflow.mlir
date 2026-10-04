cuda_tile.module @m {
  entry @attr_overflow(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 384> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8, %9, %10 = get_num_tile_blocks : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = muli %8, %11 : tile<i32>
    %13 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %14 = make_tensor_view %13, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %15[%16] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %21 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %22 = make_tensor_view %21, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %23 = make_partition_view %22 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %24, %25 = load_view_tko weak %23[%16] token=%20 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %26 = addi %19, %24 overflow<no_signed_wrap> : tile<128xi32>
    %27 = reshape %7 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<128xi32>
    %29 = iota : tile<128xi32>
    %30 = addi %28, %29 : tile<128xi32>
    %31 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %32 = broadcast %31 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %33 = offset %32, %30 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %34 = store_ptr_tko weak %33, %26 token=%25 : tile<128xptr<i32>>, tile<128xi32> -> token
    %35 = constant <i32: 128> : tile<i32>
    %36 = addi %7, %35 : tile<i32>
    %37 = subi %19, %24 overflow<no_unsigned_wrap> : tile<128xi32>
    %38 = reshape %36 : tile<i32> -> tile<1xi32>
    %39 = broadcast %38 : tile<1xi32> -> tile<128xi32>
    %40 = iota : tile<128xi32>
    %41 = addi %39, %40 : tile<128xi32>
    %42 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %43 = broadcast %42 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %44 = offset %43, %41 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %45 = store_ptr_tko weak %44, %37 token=%34 : tile<128xptr<i32>>, tile<128xi32> -> token
    %46 = constant <i32: 256> : tile<i32>
    %47 = addi %7, %46 : tile<i32>
    %48 = muli %19, %24 overflow<no_wrap> : tile<128xi32>
    %49 = reshape %47 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<128xi32>
    %51 = iota : tile<128xi32>
    %52 = addi %50, %51 : tile<128xi32>
    %53 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %54 = broadcast %53 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %55 = offset %54, %52 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %56 = store_ptr_tko weak %55, %48 token=%45 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
